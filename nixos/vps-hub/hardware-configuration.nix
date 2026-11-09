# vps-hub: Contabo VPS (instance 203736421), QEMU/KVM, virtio-scsi + virtio-net, BIOS boot.
# Written by hand from a read-only survey of the Debian image (2026-11-08); filesystems come from disko.nix.
{ lib, modulesPath, ... }:
{
  imports = [ (modulesPath + "/profiles/qemu-guest.nix") ];
  boot.initrd.availableKernelModules = [ "ata_piix" "uhci_hcd" "virtio_pci" "virtio_scsi" "virtio_net" "sd_mod" "sr_mod" ];
  nixpkgs.hostPlatform = lib.mkDefault "x86_64-linux";
}
