
static void elanmoc_cmd_ver_cb(FpiDeviceElanmoc *self, uint8_t *buffer_in,
                               gsize length_in, GError *error) {
  if (error) {
    fpi_ssm_mark_failed(self->task_ssm, error);
    return;
  }

  self->fw_ver = (buffer_in[0] << 8 | buffer_in[1]);
  fp_info("elanmoc  FW Version %x ", self->fw_ver);
  fpi_ssm_next_state(self->task_ssm);
}

static const struct elanmoc_cmd fw_ver_cmd = {
  .cmd_header = {0x40, 0x19},
  .cmd_len = 2,
  .resp_len = 2,
};