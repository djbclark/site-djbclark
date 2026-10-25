{
  # disko layout for "dann" - the entity's OVH VPS-3, 100 GB SSD, BIOS firmware.
  #
  # Verified on the box before install (2026-10-25):
  #   * /sys/firmware/efi absent  -> BIOS, so grub on the whole disk, no EFI partition
  #   * single disk sda, 100 GB   -> everything on one device
  #   * 12 GiB RAM                -> 8 GiB swap is ample for a service host
  #
  # This file is DESTRUCTIVE: applying it wipes the target disk. It exists so the layout is
  # reviewable in git rather than decided by a command line, and so a rebuild is reproducible.
  disko.devices = {
    disk.main = {
      type = "disk";
      device = "/dev/sda";
      content = {
        type = "gpt";
        partitions = {
          # No EFI system partition: the firmware is BIOS, and a stray ESP here would be dead
          # weight that a future reader would mistake for an oversight.
          #
          # `type` must be a GPT type GUID (4- or 8-4-4-4-12 hex), not a name — disko validates
          # the pattern and rejects "BIOS boot". This GUID is the BIOS boot partition type
          # (gdisk code ef02), which is what GRUB uses to embed its core image on a GPT disk.
          boot = {
            size = "1M";
            type = "21686148-6449-6E6F-744E-656564454649";
          };
          swap = {
            size = "8G";
            content = {
              type = "swap";
              # Not hibernation (this is a server); just relief for memory pressure.
              resumeDevice = false;
            };
          };
          root = {
            size = "100%";
            content = {
              type = "filesystem";
              format = "ext4";
              mountpoint = "/";
              # Labelled, so a future mount can name the filesystem rather than a /dev/sdX
              # that may move.
              extraArgs = [ "-L" "nixos-root" ];
            };
          };
        };
      };
    };
  };
}
