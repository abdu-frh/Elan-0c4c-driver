/*
 * Copyright (C) 2021 Elan Microelectronics Inc
 * Copyright (C) 2026 Abdullahi Farah <git.abdu@tutamail.com>
 *
 * This library is free software; you can redistribute it and/or
 * modify it under the terms of the GNU Lesser General Public
 * License as published by the Free Software Foundation; either
 * version 2.1 of the License, or (at your option) any later version.
 *
 * This library is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
 * Lesser General Public License for more details.
 *
 * You should have received a copy of the GNU Lesser General Public
 * License along with this library; if not, write to the Free Software
 * Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA
 */

#define FP_COMPONENT "elanmoc_0c4c"

#include "elanmoc_0c4c.h"
#include "drivers_api.h"
#include "fpi-byte-reader.h"

G_DEFINE_TYPE (FpiDeviceElanmoc0c4c, fpi_device_elanmoc_0c4c, FP_TYPE_DEVICE)

static const FpIdEntry id_table[] = {
  {
    .vid = 0x04f3,
    .pid = 0x0c4c,
  },
  {.vid = 0, .pid = 0, .driver_data = 0},
};

typedef void (*SynCmdMsgCallback)(FpiDeviceElanmoc0c4c *self,
                                  uint8_t              *buffer_in,
                                  gsize                 length_in,
                                  GError               *error);

typedef struct
{
  SynCmdMsgCallback callback;
} CommandData;

static uint8_t *
elanmoc_compose_cmd (const struct elanmoc_cmd *cmd_info)
{
  g_autofree uint8_t *cmd_buf = NULL;

  cmd_buf = g_new0 (uint8_t, cmd_info->cmd_len);
  if (cmd_info->cmd_len < ELAN_MAX_HDR_LEN)
    memcpy (cmd_buf, &cmd_info->cmd_header, cmd_info->cmd_len);
  else
    memcpy (cmd_buf, &cmd_info->cmd_header, ELAN_MAX_HDR_LEN);

  return g_steal_pointer (&cmd_buf);
}

static void
elanmoc_cmd_ack_cb (FpiDeviceElanmoc0c4c *self, uint8_t *buffer_in,
                    gsize length_in, GError *error)
{
  if (error)
    {
      fpi_ssm_mark_failed (self->task_ssm, error);
      return;
    }

  if (length_in == 0)
    {
      fpi_ssm_next_state (self->task_ssm);
      return;
    }

  if (buffer_in[0] != 0x40 && buffer_in[1] != 0x00)
    {
      fpi_ssm_mark_failed (self->task_ssm,
                           fpi_device_error_new_msg (FP_DEVICE_ERROR_PROTO,
                                                     "Can't get response!!"));
    }
  else
    {
      fpi_ssm_next_state (self->task_ssm);
    }
}

static void
fp_cmd_receive_cb (FpiUsbTransfer *transfer, FpDevice *device,
                   gpointer userdata, GError *error)
{
  FpiDeviceElanmoc0c4c *self = FPI_DEVICE_ELANMOC_0C4C (device);
  CommandData *data = userdata;
  int ssm_state = 0;

  if (error)
    {
      fpi_ssm_mark_failed (transfer->ssm, error);
      return;
    }
  if (data == NULL)
    {
      fpi_ssm_mark_failed (transfer->ssm,
                           fpi_device_error_new (FP_DEVICE_ERROR_GENERAL));
      return;
    }
  ssm_state = fpi_ssm_get_cur_state (transfer->ssm);

  /* skip zero length package */
  if (transfer->actual_length == 0)
    {
      fpi_ssm_jump_to_state (transfer->ssm, ssm_state);
      return;
    }

  if (data->callback)
    data->callback (self, transfer->buffer, transfer->actual_length, NULL);

  fpi_ssm_mark_completed (transfer->ssm);
}

typedef enum {
  ELAN_MOC_CMD_SEND = 0,
  ELAN_MOC_CMD_GET,
  ELAN_MOC_CMD_NUM_STATES,
} ElanMocCmdState;

static void
fp_cmd_run_state (FpiSsm *ssm, FpDevice *dev)
{
  FpiUsbTransfer *transfer;
  FpiDeviceElanmoc0c4c *self = FPI_DEVICE_ELANMOC_0C4C (dev);

  switch (fpi_ssm_get_cur_state (ssm))
    {
    case ELAN_MOC_CMD_SEND:
      if (self->cmd_transfer)
        {
          self->cmd_transfer->ssm = ssm;
          fpi_usb_transfer_submit (g_steal_pointer (&self->cmd_transfer),
                                   ELAN_MOC_CMD_TIMEOUT, NULL,
                                   fpi_ssm_usb_transfer_cb, NULL);
        }
      else
        {
          fpi_ssm_next_state (ssm);
        }
      break;

    case ELAN_MOC_CMD_GET:
      if (self->cmd_len_in == 0)
        {
          CommandData *data = fpi_ssm_get_data (ssm);
          if (data->callback)
            data->callback (self, NULL, 0, 0);
          fpi_ssm_mark_completed (ssm);
          return;
        }
      transfer = fpi_usb_transfer_new (dev);
      transfer->ssm = ssm;
      fpi_usb_transfer_fill_bulk (
        transfer, self->cmd_cancelable ? ELAN_EP_MOC_CMD_IN : ELAN_EP_CMD_IN,
        self->cmd_len_in);
      fpi_usb_transfer_submit (
        transfer, self->cmd_cancelable ? 0 : ELAN_MOC_CMD_TIMEOUT,
        self->cmd_cancelable ? fpi_device_get_cancellable (dev) : NULL,
        fp_cmd_receive_cb, fpi_ssm_get_data (ssm));
      break;
    }
}

static void
fp_cmd_ssm_done (FpiSsm *ssm, FpDevice *dev, GError *error)
{
  FpiDeviceElanmoc0c4c *self = FPI_DEVICE_ELANMOC_0C4C (dev);
  CommandData *data = fpi_ssm_get_data (ssm);

  self->cmd_ssm = NULL;

  if (error)
    {
      if (data->callback)
        data->callback (self, NULL, 0, error);
      else
        g_error_free (error);
    }
}

static void
fp_cmd_ssm_done_data_free (CommandData *data)
{
  g_free (data);
}

static void
elanmoc_get_cmd (FpDevice *device, guint8 *buffer_out,
                 gsize length_out, gsize length_in,
                 gboolean cancelable, SynCmdMsgCallback callback)
{
  FpiDeviceElanmoc0c4c *self = FPI_DEVICE_ELANMOC_0C4C (device);

  g_autoptr(FpiUsbTransfer) transfer = NULL;
  CommandData *data = g_new0 (CommandData, 1);

  transfer = fpi_usb_transfer_new (device);
  transfer->short_is_error = TRUE;
  fpi_usb_transfer_fill_bulk_full (transfer, ELAN_EP_CMD_OUT, buffer_out,
                                   length_out, g_free);
  data->callback = callback;

  self->cmd_transfer = g_steal_pointer (&transfer);
  self->cmd_len_in = length_in;
  self->cmd_cancelable = cancelable;

  self->cmd_ssm =
    fpi_ssm_new (FP_DEVICE (self), fp_cmd_run_state, ELAN_MOC_CMD_NUM_STATES);

  fpi_ssm_set_data (self->cmd_ssm, data,
                    (GDestroyNotify) fp_cmd_ssm_done_data_free);

  fpi_ssm_start (self->cmd_ssm, fp_cmd_ssm_done);
}

enum enroll_states {
  ENROLL_RSP_RETRY,
  ENROLL_RSP_ENROLL_REPORT,
  ENROLL_RSP_ENROLL_OK,
  ENROLL_RSP_ENROLL_CANCEL_REPORT,
  ENROLL_NUM_STATES,
};

static void
enroll_status_report (FpiDeviceElanmoc0c4c *self,
                      int enroll_status_id, int data,
                      GError *error)
{
  FpDevice *device = FP_DEVICE (self);

  if (error)
    {
      fpi_device_enroll_complete (device, NULL, error);
      return;
    }

  switch (enroll_status_id)
    {
    case ENROLL_RSP_RETRY: {
        fpi_device_enroll_progress (
          device, self->num_frames, NULL,
          fpi_device_retry_new (FP_DEVICE_RETRY_CENTER_FINGER));
        break;
      }

    case ENROLL_RSP_ENROLL_REPORT: {
        fpi_device_enroll_progress (device, self->num_frames, NULL, NULL);
        break;
      }

    case ENROLL_RSP_ENROLL_OK: {
        FpPrint *print = NULL;
        fp_info ("Enrollment was successful!");
        fpi_device_get_enroll_data (device, &print);
        fpi_device_enroll_complete (device, g_object_ref (print), NULL);
        break;
      }

    case ENROLL_RSP_ENROLL_CANCEL_REPORT: {
        fpi_device_enroll_complete (
          device, NULL,
          fpi_device_error_new_msg (
            FP_DEVICE_ERROR_GENERAL,
            "Enrollment failed (%d) (ENROLL_RSP_ENROLL_CANCEL_REPORT)", data));
      }
    }
}

static void
elanmoc_get_enrolled_cb (FpiDeviceElanmoc0c4c *self,
                         uint8_t *buffer_in, gsize length_in,
                         GError *error)
{
  if (error)
    {
      fpi_ssm_mark_failed (self->task_ssm, error);
      return;
    }

  if (buffer_in[0] != 0x40)
    {
      fpi_ssm_mark_failed (self->task_ssm,
                           fpi_device_error_new_msg (FP_DEVICE_ERROR_PROTO,
                                                     "Can't get response!!"));
    }
  else
    {
      fp_info (
        "elanmoc Current enrolled fingers in the Chipset: %d (0x%.2X 0x%.2X)",
        buffer_in[1], buffer_in[0], buffer_in[1]);
      self->curr_enrolled = buffer_in[1];
      fpi_ssm_next_state (self->task_ssm);
    }
}

static void
elanmoc_enroll_cb (FpiDeviceElanmoc0c4c *self, uint8_t *buffer_in,
                   gsize length_in, GError *error)
{
  if (error)
    {
      fpi_ssm_mark_failed (self->task_ssm, error);
      return;
    }

  if (buffer_in[0] != 0x40)
    {
      fpi_ssm_mark_failed (self->task_ssm,
                           fpi_device_error_new_msg (FP_DEVICE_ERROR_PROTO,
                                                     "Can't get response!!"));
    }
  else
    {
      if (buffer_in[1] == ELAN_MSG_OK)
        {
          self->num_frames += 1;
          enroll_status_report (self, ENROLL_RSP_ENROLL_REPORT, self->num_frames,
                                NULL);
        }
      else
        {
          enroll_status_report (self, ENROLL_RSP_RETRY, self->num_frames, NULL);
        }

      if (self->num_frames == self->max_moc_enroll_time &&
          buffer_in[1] == ELAN_MSG_OK)
        fpi_ssm_next_state (self->task_ssm);
      else if (self->num_frames < self->max_moc_enroll_time)
        fpi_ssm_jump_to_state (self->task_ssm, MOC_ENROLL_WAIT_FINGER);
      else
        fpi_ssm_mark_failed (self->task_ssm, error);
    }
}

static void
elanmoc_enroll_collision_cb (FpiDeviceElanmoc0c4c *self,
                             uint8_t *buffer_in, gsize length_in,
                             GError *error)
{
  if (error)
    {
      fpi_ssm_mark_failed (self->task_ssm, error);
      return;
    }

  if (buffer_in[0] != 0x40)
    {
      fpi_ssm_mark_failed (
        self->task_ssm,
        fpi_device_error_new_msg (
          FP_DEVICE_ERROR_PROTO,
          "Collision check: unexpected response header 0x%.2X",
          buffer_in[0]));
      return;
    }

  if (buffer_in[1] != ELAN_MSG_OK)
    {
      fp_warn ("elanmoc collision detected: finger already enrolled at slot %d",
               (int) buffer_in[2]);
      fpi_ssm_mark_failed (self->task_ssm,
                           fpi_device_error_new (FP_DEVICE_ERROR_DATA_DUPLICATE));
      return;
    }

  fp_info ("elanmoc collision check passed — no duplicate found");
  fpi_ssm_next_state (self->task_ssm);
}

static void
elanmoc_commit_cb (FpiDeviceElanmoc0c4c *self, uint8_t *buffer_in,
                   gsize length_in, GError *error)
{
  if (error)
    {
      fpi_ssm_mark_failed (self->task_ssm, error);
      return;
    }

  if (length_in == 0)
    {
      fpi_ssm_next_state (self->task_ssm);
      return;
    }

  if (buffer_in[0] != 0x40 && buffer_in[1] != 0x00)
    {
      fpi_ssm_mark_failed (self->task_ssm,
                           fpi_device_error_new_msg (FP_DEVICE_ERROR_PROTO,
                                                     "Can't get response!!"));
    }
  else
    {
      fp_info ("elanmoc_commit_cb success");
      enroll_status_report (self, ENROLL_RSP_ENROLL_OK, self->num_frames, NULL);
      fpi_ssm_next_state (self->task_ssm);
    }
}

static void
elan_enroll_run_state (FpiSsm *ssm, FpDevice *dev)
{
  FpiDeviceElanmoc0c4c *self = FPI_DEVICE_ELANMOC_0C4C (dev);
  guint8 *cmd_buf = NULL;
  guint8 *data = NULL;

  switch (fpi_ssm_get_cur_state (ssm))
    {
    case MOC_ENROLL_GET_ENROLLED_NUM:
      cmd_buf = elanmoc_compose_cmd (&enrolled_number_cmd);
      elanmoc_get_cmd (dev, cmd_buf, enrolled_number_cmd.cmd_len,
                       enrolled_number_cmd.resp_len, 0, elanmoc_get_enrolled_cb);
      break;

    case MOC_ENROLL_WAIT_FINGER:
      cmd_buf = elanmoc_compose_cmd (&elanmoc_enroll_cmd);
      cmd_buf[3] = self->curr_enrolled;
      cmd_buf[4] = self->max_moc_enroll_time;
      cmd_buf[5] = self->num_frames;
      elanmoc_get_cmd (dev, cmd_buf, elanmoc_enroll_cmd.cmd_len,
                       elanmoc_enroll_cmd.resp_len, 1, elanmoc_enroll_cb);
      break;

    case MOC_ENROLL_CHECK_COLLISION:
      cmd_buf = elanmoc_compose_cmd (&elanmoc_enroll_collision_cmd);
      elanmoc_get_cmd (dev, cmd_buf, elanmoc_enroll_collision_cmd.cmd_len,
                       elanmoc_enroll_collision_cmd.resp_len, 0,
                       elanmoc_enroll_collision_cb);
      break;

    case MOC_ENROLL_COMMIT_RESULT:
      data = fpi_ssm_get_data (ssm);
      cmd_buf = g_malloc0 (elanmoc_enroll_commit_cmd.cmd_len);
      memcpy (cmd_buf, &elanmoc_enroll_commit_cmd.cmd_header, ELAN_MAX_HDR_LEN);
      memcpy (cmd_buf + ELAN_MAX_HDR_LEN, data, ELAN_SID_LEN);
      elanmoc_get_cmd (dev, cmd_buf, elanmoc_enroll_commit_cmd.cmd_len,
                       elanmoc_enroll_commit_cmd.resp_len, 0, elanmoc_commit_cb);
      break;
    }
}

static void
task_ssm_done (FpiSsm *ssm, FpDevice *dev, GError *error)
{
  FpiDeviceElanmoc0c4c *self = FPI_DEVICE_ELANMOC_0C4C (dev);

  self->task_ssm = NULL;
  g_clear_pointer (&self->list_result, g_ptr_array_unref);

  if (error)
    fpi_device_action_error (dev, error);
}

static void
elanmoc_list_verify_cb (FpiDeviceElanmoc0c4c *self,
                        uint8_t *buffer_in, gsize length_in,
                        GError *error)
{
  if (error)
    {
      fpi_ssm_mark_failed (self->task_ssm, error);
      return;
    }
  fpi_ssm_next_state (self->task_ssm);
}

static void
elanmoc_get_finger_info_cb (FpiDeviceElanmoc0c4c *self,
                            uint8_t *buffer_in, gsize length_in,
                            GError *error)
{

  FpPrint *print;
  GVariant *data;
  GVariant *uid;
  g_autofree gchar *userid_safe = NULL;
  guint8 userid_len;

  if (error)
    {
      fpi_ssm_mark_failed (self->task_ssm, error);
      return;
    }

  self->list_index++;

  if (buffer_in[1] == ELAN_MSG_NOT_READY || buffer_in[1] != ELAN_MSG_OK)
    goto next;

  userid_len = buffer_in[3];
  if (userid_len == 0 || (gsize) (userid_len + 4) > length_in)
    goto next;

  userid_safe = g_strndup ((const char *) &buffer_in[4], userid_len);
  uid = g_variant_new_fixed_array (G_VARIANT_TYPE_BYTE, &buffer_in[4],
                                   userid_len, 1);
  data = g_variant_new ("(yy@ay)", buffer_in[1], buffer_in[2], uid);

  print = fp_print_new (FP_DEVICE (self));
  fpi_print_set_type (print, FPI_PRINT_RAW);
  fpi_print_set_device_stored (print, TRUE);
  g_object_set (print, "fpi-data", data, NULL);
  g_object_set (print, "description", userid_safe, NULL);
  fpi_print_fill_from_user_id (print, userid_safe);

  g_ptr_array_add (self->list_result, g_object_ref_sink (print));

next:
  if (self->list_index < ELAN_MAX_ENROLL_NUM)
    {
      fpi_ssm_jump_to_state (self->task_ssm, MOC_LIST_GET_FINGER);
    }
  else
    {
      fpi_device_list_complete (FP_DEVICE (self),
                                g_steal_pointer (&self->list_result), NULL);
      fpi_ssm_next_state (self->task_ssm);
    }
}

static void
elan_list_run_state (FpiSsm *ssm, FpDevice *dev)
{
  FpiDeviceElanmoc0c4c *self = FPI_DEVICE_ELANMOC_0C4C (dev);
  guint8 *cmd_buf = NULL;

  switch (fpi_ssm_get_cur_state (ssm))
    {
    case MOC_LIST_VERIFY_UNLOCK:
      fp_info ("elanmoc list: sending verify to unlock finger_info");
      cmd_buf = elanmoc_compose_cmd (&elanmoc_verify_cmd);
      elanmoc_get_cmd (dev, cmd_buf, elanmoc_verify_cmd.cmd_len,
                       elanmoc_verify_cmd.resp_len,
                       1, /* cancelable, reads EP 0x84 */
                       elanmoc_list_verify_cb);
      break;

    case MOC_LIST_GET_ENROLLED:
      cmd_buf = elanmoc_compose_cmd (&enrolled_number_cmd);
      elanmoc_get_cmd (dev, cmd_buf, enrolled_number_cmd.cmd_len,
                       enrolled_number_cmd.resp_len, 0, elanmoc_get_enrolled_cb);
      self->list_index = 0;
      break;

    case MOC_LIST_GET_FINGER:
      cmd_buf = elanmoc_compose_cmd (&elanmoc_finger_info_cmd);
      cmd_buf[3] = self->list_index;
      elanmoc_get_cmd (dev, cmd_buf, elanmoc_finger_info_cmd.cmd_len,
                       elanmoc_finger_info_cmd.resp_len, 0,
                       elanmoc_get_finger_info_cb);
      break;
    }
}

static void
elanmoc_list (FpDevice *device)
{
  FpiDeviceElanmoc0c4c *self = FPI_DEVICE_ELANMOC_0C4C (device);

  self->list_result = g_ptr_array_new_with_free_func (g_object_unref);
  self->task_ssm =
    fpi_ssm_new (FP_DEVICE (self), elan_list_run_state, MOC_LIST_NUM_STATES);
  fpi_ssm_start (self->task_ssm, task_ssm_done);
}

enum verify_status {
  RSP_VERIFY_FAIL,
  RSP_VERIFY_OK,
  RSP_VERIFY_STATES,
};

static void
elanmoc_match_report_cb (FpiDeviceElanmoc0c4c *self,
                         uint8_t *buffer_in, gsize length_in,
                         GError *error)
{
  FpDevice *device = FP_DEVICE (self);
  FpPrint *print = NULL;
  FpPrint *verify_print = NULL;
  GPtrArray *prints;
  GVariant *data;
  GVariant *uid;
  g_autofree gchar *userid_safe = NULL;
  guint8 userid_len;
  gboolean found = FALSE;
  guint index;

  if (error)
    {
      fpi_ssm_mark_failed (self->task_ssm, error);
      return;
    }

  if (buffer_in[0] != 0x40 || buffer_in[1] != ELAN_MSG_OK)
    {
      fpi_ssm_mark_failed (self->task_ssm,
                           fpi_device_error_new_msg (
                             FP_DEVICE_ERROR_PROTO,
                             "match report: unexpected response 0x%.2X 0x%.2X",
                             buffer_in[0], buffer_in[1]));
      return;
    }

  userid_len = buffer_in[3];
  if (userid_len == 0 || (gsize) (userid_len + 4) > length_in)
    {
      fpi_ssm_mark_failed (self->task_ssm,
                           fpi_device_error_new_msg (
                             FP_DEVICE_ERROR_PROTO,
                             "match report: bad userid_len %d", userid_len));
      return;
    }

  userid_safe = g_strndup ((const char *) &buffer_in[4], userid_len);
  uid = g_variant_new_fixed_array (G_VARIANT_TYPE_BYTE, &buffer_in[4],
                                   userid_len, 1);
  data = g_variant_new ("(yy@ay)", buffer_in[1], buffer_in[2], uid);

  print = fp_print_new (device);
  fpi_print_set_type (print, FPI_PRINT_RAW);
  fpi_print_set_device_stored (print, TRUE);
  g_object_set (print, "fpi-data", data, NULL);
  g_object_set (print, "description", userid_safe, NULL);
  fpi_print_fill_from_user_id (print, userid_safe);

  fp_info ("Verify/Identify successful for: %s", userid_safe);

  if (fpi_device_get_current_action (device) == FPI_DEVICE_ACTION_IDENTIFY)
    {
      fpi_device_get_identify_data (device, &prints);
      found = g_ptr_array_find_with_equal_func (
        prints, print, (GEqualFunc) fp_print_equal, &index);
      if (found)
        fpi_device_identify_report (device, g_ptr_array_index (prints, index),
                                    print, NULL);
      else
        fpi_device_identify_report (device, NULL, print, NULL);
      fpi_device_identify_complete (device, NULL);
    }
  else
    {
      fpi_device_get_verify_data (device, &verify_print);
      if (fp_print_equal (verify_print, print))
        fpi_device_verify_report (device, FPI_MATCH_SUCCESS, print, NULL);
      else
        fpi_device_verify_report (device, FPI_MATCH_FAIL, print, NULL);
      fpi_device_verify_complete (device, NULL);
    }
  fpi_ssm_next_state (self->task_ssm);
}

static void
identify_status_report (FpiDeviceElanmoc0c4c *self,
                        int verify_status_id, int data,
                        GError *error)
{
  FpDevice *device = FP_DEVICE (self);
  guint8 *cmd_buf = NULL;

  if (error)
    {
      if (fpi_device_get_current_action (device) == FPI_DEVICE_ACTION_VERIFY)
        fpi_device_verify_complete (device, error);
      else
        fpi_device_identify_complete (device, error);
      return;
    }

  switch (verify_status_id)
    {
    case RSP_VERIFY_FAIL: {
        if (data == ELAN_MSG_VERIFY_ERR)
          {
            if (fpi_device_get_current_action (device) == FPI_DEVICE_ACTION_VERIFY)
              {
                fpi_device_verify_report (device, FPI_MATCH_FAIL, NULL, NULL);
                fpi_device_verify_complete (device, NULL);
              }
            else
              {
                fpi_device_identify_report (device, NULL, NULL, NULL);
                fpi_device_identify_complete (device, NULL);
              }
          }
        else
          {
            GError *retry_error;

            switch (data)
              {
              case ELAN_MSG_TOO_HIGH:
              case ELAN_MSG_TOO_LOW:
              case ELAN_MSG_TOO_RIGHT:
              case ELAN_MSG_TOO_LEFT:
                retry_error = fpi_device_retry_new (FP_DEVICE_RETRY_CENTER_FINGER);
                break;

              default:
                retry_error = fpi_device_retry_new (FP_DEVICE_RETRY_GENERAL);
              }

            if (fpi_device_get_current_action (device) == FPI_DEVICE_ACTION_VERIFY)
              {
                fpi_device_verify_report (device, FPI_MATCH_ERROR, NULL, retry_error);
                fpi_device_verify_complete (device, NULL);
              }
            else
              {
                fpi_device_identify_report (device, NULL, NULL, retry_error);
                fpi_device_identify_complete (device, NULL);
              }
          }
        break;
      }

    case RSP_VERIFY_OK: {
        fp_dbg ("Verify was successful! for user: %d mesg_code: %d ", data,
                verify_status_id);
        cmd_buf = elanmoc_compose_cmd (&elanmoc_finger_info_cmd);
        cmd_buf[3] = data;
        elanmoc_get_cmd (device, cmd_buf, elanmoc_finger_info_cmd.cmd_len,
                         elanmoc_finger_info_cmd.resp_len, 0,
                         elanmoc_match_report_cb);
        break;
      }
    }
}

enum identify_states {
  IDENTIFY_SET_MODE,
  IDENTIFY_WAIT_FINGER,
  IDENTIFY_NUM_STATES,
};

static void
elanmoc_identify_cb (FpiDeviceElanmoc0c4c *self, uint8_t *buffer_in,
                     gsize length_in, GError *error)
{
  if (error)
    {
      fpi_ssm_mark_failed (self->task_ssm, error);
      return;
    }

  if (buffer_in[1] == ELAN_MSG_VERIFY_ERR)
    {
      identify_status_report (self, RSP_VERIFY_FAIL, buffer_in[1], error);
      fpi_ssm_next_state (self->task_ssm);
    }
  else if (buffer_in[1] <= ELAN_MAX_ENROLL_NUM)
    {
      identify_status_report (self, RSP_VERIFY_OK, buffer_in[1], error);
    }
  else
    {
      identify_status_report (self, RSP_VERIFY_FAIL, buffer_in[1], error);
      fpi_ssm_next_state (self->task_ssm);
    }
}

static void
elan_identify_run_state (FpiSsm *ssm, FpDevice *dev)
{
  guint8 *cmd_buf = NULL;

  fp_info ("elanmoc %s ", __func__);
  switch (fpi_ssm_get_cur_state (ssm))
    {
    case IDENTIFY_SET_MODE:
      fp_info ("elanmoc %s IDENTIFY_SET_MODE", __func__);
      cmd_buf = elanmoc_compose_cmd (&elanmoc_set_mod_cmd);
      cmd_buf[3] = 0x00;
      elanmoc_get_cmd (dev, cmd_buf, elanmoc_set_mod_cmd.cmd_len,
                       elanmoc_set_mod_cmd.resp_len, 0, elanmoc_cmd_ack_cb);
      break;

    case IDENTIFY_WAIT_FINGER:
      fp_info ("elanmoc %s VERIFY_WAIT_FINGER", __func__);
      cmd_buf = elanmoc_compose_cmd (&elanmoc_verify_cmd);
      elanmoc_get_cmd (dev, cmd_buf, elanmoc_verify_cmd.cmd_len,
                       elanmoc_verify_cmd.resp_len, 1, elanmoc_identify_cb);
      break;
    }
}

static void
elanmoc_enroll (FpDevice *device)
{
  FpiDeviceElanmoc0c4c *self = FPI_DEVICE_ELANMOC_0C4C (device);
  FpPrint *print = NULL;
  GVariant *data = NULL;
  GVariant *uid = NULL;
  g_autofree gchar *user_id = NULL;
  gsize user_id_len;
  guint8 *userdata = g_malloc0 (ELAN_USERDATE_SIZE);

  fpi_device_get_enroll_data (device, &print);
  user_id = fpi_print_generate_user_id (print);
  user_id_len = strlen (user_id);
  user_id_len = MIN (ELAN_MAX_USER_ID_LEN, user_id_len);

  uid = g_variant_new_fixed_array (G_VARIANT_TYPE_BYTE, user_id, user_id_len, 1);

  data = g_variant_new ("(yy@ay)", 0, 0, uid);

  fpi_print_set_type (print, FPI_PRINT_RAW);
  fpi_print_set_device_stored (print, TRUE);
  g_object_set (print, "fpi-data", data, NULL);
  g_object_set (print, "description", user_id, NULL);

  userdata[0] = 0;
  userdata[1] = 0;
  userdata[2] = user_id_len;

  memcpy (userdata + 3, user_id, user_id_len);
  self->task_ssm = fpi_ssm_new (FP_DEVICE (self), elan_enroll_run_state,
                                MOC_ENROLL_NUM_STATES);
  fpi_ssm_set_data (self->task_ssm, userdata,
                    (GDestroyNotify) fp_cmd_ssm_done_data_free);
  fpi_ssm_start (self->task_ssm, task_ssm_done);
}

static void
elanmoc_delete_cb (FpiDeviceElanmoc0c4c *self, uint8_t *buffer_in,
                   gsize length_in, GError *error)
{
  if (error)
    {
      fpi_ssm_mark_failed (self->task_ssm, error);
      return;
    }
  if (buffer_in[0] != 0x40 && buffer_in[1] != 0x00)
    {
      fpi_ssm_mark_failed (self->task_ssm,
                           fpi_device_error_new_msg (FP_DEVICE_ERROR_PROTO,
                                                     "Can't get response!!"));
    }
  else
    {
      fpi_device_delete_complete (FP_DEVICE (self), NULL);
      fpi_ssm_next_state (self->task_ssm);
    }
}

static void
elan_delete_run_state (FpiSsm *ssm, FpDevice *dev)
{
  guint8 *cmd_buf = NULL;
  guint8 *data = fpi_ssm_get_data (ssm);

  switch (fpi_ssm_get_cur_state (ssm))
    {
    case DELETE_SEND_CMD:
      cmd_buf = g_malloc0 (elanmoc_delete_cmd.cmd_len + ELAN_USERDATE_SIZE);
      memcpy (cmd_buf, &elanmoc_delete_cmd.cmd_header, ELAN_MAX_HDR_LEN);
      memcpy (cmd_buf + 3, data, ELAN_USERDATE_SIZE);
      elanmoc_get_cmd (dev, cmd_buf, elanmoc_delete_cmd.cmd_len,
                       elanmoc_delete_cmd.resp_len, 0, elanmoc_delete_cb);
      break;
    }
}

static void
elanmoc_delete_print (FpDevice *device)
{
  g_autoptr(GVariant) data = NULL;
  g_autoptr(GVariant) user_id_var = NULL;
  FpiDeviceElanmoc0c4c *self = FPI_DEVICE_ELANMOC_0C4C (device);
  FpPrint *print = NULL;
  const guint8 *user_id;
  g_autofree char *user_id_safe = NULL;
  gsize user_id_len = 0;
  guint8 *userid_buf = NULL;

  fpi_device_get_delete_data (device, &print);
  g_object_get (print, "fpi-data", &data, NULL);

  if (!g_variant_check_format_string (data, "(yy@ay)", FALSE))
    {
      fpi_device_delete_complete (
        device, fpi_device_error_new (FP_DEVICE_ERROR_DATA_INVALID));
      return;
    }

  userid_buf = g_malloc0 (ELAN_USERDATE_SIZE);

  g_variant_get (data, "(yy@ay)", &userid_buf[0], &userid_buf[1], &user_id_var);
  user_id = g_variant_get_fixed_array (user_id_var, &user_id_len, 1);
  user_id_safe = g_strndup ((const char *) user_id, user_id_len);
  user_id_len = MIN (ELAN_MAX_USER_ID_LEN, user_id_len);
  userid_buf[2] = user_id_len;
  memcpy (userid_buf + 3, user_id, user_id_len);

  fp_info ("Delete Finger, user_id = %s!", user_id_safe);
  self->task_ssm =
    fpi_ssm_new (device, elan_delete_run_state, DELETE_NUM_STATES);
  fpi_ssm_set_data (self->task_ssm, userid_buf, g_free);
  fpi_ssm_start (self->task_ssm, task_ssm_done);
}

static void
elanmoc_identify (FpDevice *device)
{
  FpiDeviceElanmoc0c4c *self = FPI_DEVICE_ELANMOC_0C4C (device);

  self->task_ssm =
    fpi_ssm_new (device, elan_identify_run_state, IDENTIFY_NUM_STATES);
  fpi_ssm_start (self->task_ssm, task_ssm_done);
}

enum clear_storage_states {
  CLEAR_SEND_CMD,
  CLEAR_NUM_STATES,
};

static void
elanmoc_clear_storage_cb (FpiDeviceElanmoc0c4c *self,
                          uint8_t *buffer_in, gsize length_in,
                          GError *error)
{
  if (error)
    {
      fpi_ssm_mark_failed (self->task_ssm, error);
      return;
    }

  fp_info ("elanmoc clear storage complete");
  fpi_ssm_next_state (self->task_ssm);
}

static void
task_ssm_clear_storage_done (FpiSsm *ssm, FpDevice *dev,
                             GError *error)
{
  FpiDeviceElanmoc0c4c *self = FPI_DEVICE_ELANMOC_0C4C (dev);

  self->task_ssm = NULL;
  fpi_device_clear_storage_complete (dev, error);
}

static void
elan_clear_storage_run_state (FpiSsm *ssm, FpDevice *dev)
{
  guint8 *cmd_buf = NULL;

  switch (fpi_ssm_get_cur_state (ssm))
    {
    case CLEAR_SEND_CMD:
      fp_info ("elanmoc sending remove-all command");
      cmd_buf = elanmoc_compose_cmd (&elanmoc_remove_all_cmd);
      elanmoc_get_cmd (dev, cmd_buf, elanmoc_remove_all_cmd.cmd_len,
                       elanmoc_remove_all_cmd.resp_len, 0,
                       elanmoc_clear_storage_cb);
      break;
    }
}

static void
elanmoc_clear_storage (FpDevice *device)
{
  FpiDeviceElanmoc0c4c *self = FPI_DEVICE_ELANMOC_0C4C (device);

  fp_info ("elanmoc clear_storage: wiping all enrolled fingers from sensor");
  self->task_ssm =
    fpi_ssm_new (device, elan_clear_storage_run_state, CLEAR_NUM_STATES);
  fpi_ssm_start (self->task_ssm, task_ssm_clear_storage_done);
}

static void
task_ssm_init_done (FpiSsm *ssm, FpDevice *dev, GError *error)
{
  FpiDeviceElanmoc0c4c *self = FPI_DEVICE_ELANMOC_0C4C (dev);

  if (error)
    g_usb_device_release_interface (fpi_device_get_usb_device (dev), 0, 0, NULL);

  fpi_device_open_complete (FP_DEVICE (self), error);
}

static void
elanmoc_cmd_ver_cb (FpiDeviceElanmoc0c4c *self, uint8_t *buffer_in,
                    gsize length_in, GError *error)
{
  if (error)
    {
      fpi_ssm_mark_failed (self->task_ssm, error);
      return;
    }

  self->fw_ver = (buffer_in[0] << 8 | buffer_in[1]);
  fp_info ("elanmoc  FW Version %x ", self->fw_ver);
  fpi_ssm_next_state (self->task_ssm);
}

static void
elanmoc_cmd_dim_cb (FpiDeviceElanmoc0c4c *self, uint8_t *buffer_in,
                    gsize length_in, GError *error)
{
  if (error)
    {
      fpi_ssm_mark_failed (self->task_ssm, error);
      return;
    }

  self->x_trace = buffer_in[0] + 1;
  self->y_trace = buffer_in[2] + 1;
  fp_info ("elanmoc last_read DIM 0x%.2X(%d) 0x%.2X(%d)", self->x_trace,
           self->x_trace, self->y_trace, self->y_trace);
  fpi_ssm_next_state (self->task_ssm);
}

static void
elanmoc_get_status_cb (FpiDeviceElanmoc0c4c *self,
                       uint8_t *buffer_in, gsize length_in,
                       GError *error)
{
  guint8 *cmd_buf = NULL;

  if (error)
    {
      fpi_ssm_mark_failed (self->task_ssm, error);
      return;
    }

  if (buffer_in[1] != 0x03 && self->cmd_retry_cnt != 0)
    {
      self->cmd_retry_cnt--;
      cmd_buf = elanmoc_compose_cmd (&cal_status_cmd);
      elanmoc_get_cmd (FP_DEVICE (self), cmd_buf, cal_status_cmd.cmd_len,
                       cal_status_cmd.resp_len, 0, elanmoc_get_status_cb);
    }
  else
    {
      if (self->cmd_retry_cnt == 0)
        {
          fpi_ssm_mark_failed (
            self->task_ssm,
            fpi_device_error_new_msg (FP_DEVICE_ERROR_PROTO, "Sensor not ready"));
          return;
        }
      fpi_ssm_next_state (self->task_ssm);
    }
}

static void
dev_init_handler (FpiSsm *ssm, FpDevice *dev)
{
  FpiDeviceElanmoc0c4c *self = FPI_DEVICE_ELANMOC_0C4C (dev);
  guint8 *cmd_buf = NULL;

  switch (fpi_ssm_get_cur_state (ssm))
    {
    case DEV_WAIT_READY:
      self->cmd_retry_cnt = ELAN_MOC_CAL_RETRY;
      cmd_buf = elanmoc_compose_cmd (&cal_status_cmd);
      elanmoc_get_cmd (dev, cmd_buf, cal_status_cmd.cmd_len,
                       cal_status_cmd.resp_len, 0, elanmoc_get_status_cb);
      break;

    case DEV_SET_MODE:
      cmd_buf = elanmoc_compose_cmd (&elanmoc_set_mod_cmd);
      cmd_buf[3] = 0x00;
      elanmoc_get_cmd (dev, cmd_buf, elanmoc_set_mod_cmd.cmd_len,
                       elanmoc_set_mod_cmd.resp_len, 0, elanmoc_cmd_ack_cb);
      break;

    case DEV_GET_VER:
      cmd_buf = elanmoc_compose_cmd (&fw_ver_cmd);
      elanmoc_get_cmd (dev, cmd_buf, fw_ver_cmd.cmd_len, fw_ver_cmd.resp_len, 0,
                       elanmoc_cmd_ver_cb);
      break;

    case DEV_GET_DIM:
      cmd_buf = elanmoc_compose_cmd (&sensor_dim_cmd);
      elanmoc_get_cmd (dev, cmd_buf, sensor_dim_cmd.cmd_len,
                       sensor_dim_cmd.resp_len, 0, elanmoc_cmd_dim_cb);
      break;

    case DEV_GET_ENROLLED:
      cmd_buf = elanmoc_compose_cmd (&enrolled_number_cmd);
      elanmoc_get_cmd (dev, cmd_buf, enrolled_number_cmd.cmd_len,
                       enrolled_number_cmd.resp_len, 0, elanmoc_get_enrolled_cb);
      break;
    }
}

static void
elanmoc_open (FpDevice *device)
{
  FpiDeviceElanmoc0c4c *self = FPI_DEVICE_ELANMOC_0C4C (device);
  GError *error = NULL;
  gint productid = 0;

  if (!g_usb_device_claim_interface (fpi_device_get_usb_device (device), 0, 0,
                                     &error))
    goto error;

  productid = g_usb_device_get_pid (fpi_device_get_usb_device (device));
  switch (productid)
    {
    case 0x0c8c:
      self->max_moc_enroll_time = 11;
      break;

    case 0x0c99:
      self->max_moc_enroll_time = 14;
      break;

    case 0x0c8d:
      self->max_moc_enroll_time = 17;
      break;

    case 0x0c4c:
      self->max_moc_enroll_time = 8;
      break;

    default:
      self->max_moc_enroll_time = ELAN_MOC_ENROLL_TIMES;
      break;
    }

  fpi_device_set_nr_enroll_stages (device, self->max_moc_enroll_time);

  self->task_ssm =
    fpi_ssm_new (FP_DEVICE (self), dev_init_handler, DEV_INIT_STATES);
  fpi_ssm_start (self->task_ssm, task_ssm_init_done);
  return;

error:
  fpi_device_open_complete (FP_DEVICE (self), error);
}

static void
task_ssm_exit_done (FpiSsm *ssm, FpDevice *dev, GError *error)
{
  FpiDeviceElanmoc0c4c *self = FPI_DEVICE_ELANMOC_0C4C (dev);

  g_usb_device_release_interface (fpi_device_get_usb_device (FP_DEVICE (self)), 0,
                                  0, &error);
  fpi_device_close_complete (FP_DEVICE (self), error);
  self->task_ssm = NULL;
}

static void
dev_exit_handler (FpiSsm *ssm, FpDevice *dev)
{
  guint8 *cmd_buf = NULL;

  switch (fpi_ssm_get_cur_state (ssm))
    {
    case DEV_EXIT_ABORT:
      cmd_buf = elanmoc_compose_cmd (&elanmoc_abort_cmd);
      elanmoc_get_cmd (dev, cmd_buf, elanmoc_abort_cmd.cmd_len,
                       elanmoc_abort_cmd.resp_len, 0, elanmoc_cmd_ack_cb);
      break;
    }
}

static void
elanmoc_close (FpDevice *device)
{
  FpiDeviceElanmoc0c4c *self = FPI_DEVICE_ELANMOC_0C4C (device);

  fp_info ("Elanmoc dev_exit");
  self->task_ssm =
    fpi_ssm_new (FP_DEVICE (self), dev_exit_handler, DEV_EXIT_STATES);
  fpi_ssm_start (self->task_ssm, task_ssm_exit_done);
}

static void
fpi_device_elanmoc_0c4c_init (FpiDeviceElanmoc0c4c *self)
{
  G_DEBUG_HERE ();
}

static void
fpi_device_elanmoc_0c4c_class_init (FpiDeviceElanmoc0c4cClass *klass)
{
  FpDeviceClass *dev_class = FP_DEVICE_CLASS (klass);

  dev_class->id = FP_COMPONENT;
  dev_class->full_name = ELAN_MOC_DRIVER_FULLNAME;

  dev_class->type = FP_DEVICE_TYPE_USB;
  dev_class->scan_type = FP_SCAN_TYPE_PRESS;
  dev_class->id_table = id_table;
  dev_class->nr_enroll_stages = ELAN_MOC_ENROLL_TIMES;
  dev_class->temp_hot_seconds = -1;

  dev_class->open = elanmoc_open;
  dev_class->close = elanmoc_close;
  dev_class->verify = elanmoc_identify;
  dev_class->enroll = elanmoc_enroll;
  dev_class->identify = elanmoc_identify;
  dev_class->delete = elanmoc_delete_print;
  dev_class->list = elanmoc_list;
  dev_class->clear_storage = elanmoc_clear_storage;
  dev_class->features |= FP_DEVICE_FEATURE_DUPLICATES_CHECK;

  fpi_device_class_auto_initialize_features (dev_class);
}
