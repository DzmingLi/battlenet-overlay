# One nixpkgs runtime shared by every Linux game.
{ wineWow64Packages, dxvk, lib }:
{
  wine = wineWow64Packages.unstable;
  dxvk = lib.getBin dxvk;
}
