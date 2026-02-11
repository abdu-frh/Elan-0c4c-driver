
struct elanmoc_cmd
{
  unsigned char cmd_header[ELAN_MAX_HDR_LEN];
  int           cmd_len;
  int           resp_len;
};

static const struct elanmoc_cmd fw_ver_cmd = {
  .cmd_header = {0x40, 0x19},
  .cmd_len = 2,
  .resp_len = 2,
};