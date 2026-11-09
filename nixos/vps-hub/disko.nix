# vps-hub disk: GPT with a BIOS boot partition (Contabo boots by BIOS), an ESP so it can also boot
# by UEFI, and ext4 root. Swap is a file-less 4 GiB partition.
{
  disko.devices.disk.main = {
    type = "disk";
    device = "/dev/disk/by-id/scsi-0QEMU_QEMU_HARDDISK_drive-scsi0";
    content = {
      type = "gpt";
      partitions = {
        boot = { size = "1M"; type = "EF02"; priority = 1; };
        ESP = {
          size = "512M";
          type = "EF00";
          content = { type = "filesystem"; format = "vfat"; mountpoint = "/boot"; mountOptions = [ "umask=0077" ]; };
        };
        swap = { size = "4G"; content = { type = "swap"; }; };
        root = {
          size = "100%";
          content = { type = "filesystem"; format = "ext4"; mountpoint = "/"; };
        };
      };
    };
  };
}
