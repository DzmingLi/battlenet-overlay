{ lib, system ? "x86_64-linux" }:
let
  directory = ./games;
  darwin = lib.hasSuffix "-darwin" system;
  suffix = if darwin then ".mac.nix" else ".nix";
  names = lib.filter (name: builtins.match (if darwin then "[a-z0-9_-]+\\.mac\\.nix" else "[a-z0-9_-]+\\.nix") name != null)
    (builtins.attrNames (builtins.readDir directory));
in builtins.listToAttrs (map (name: {
  name = lib.removeSuffix suffix name;
  value = let
    product = lib.removeSuffix suffix name;
    prefix = product + (if darwin then ".mac." else ".");
    variants = lib.filter (file: lib.hasPrefix prefix file && lib.hasSuffix ".nix" file)
      (builtins.attrNames (builtins.readDir directory));
  in (import (directory + "/${name}")) // {
    locales = builtins.listToAttrs (map (file: {
      name = lib.removeSuffix ".nix" (lib.removePrefix prefix file);
      value = import (directory + "/${file}");
    }) (lib.filter (file: builtins.match "[a-z]{2}[A-Z]{2}\\.nix" (lib.removePrefix prefix file) != null) variants));
    chinaLocales = builtins.listToAttrs (map (file: {
      name = lib.removeSuffix ".nix" (lib.removePrefix "${product}.cn." file);
      value = import (directory + "/${file}");
    }) (lib.filter (file: !darwin && builtins.match "cn\\.[a-z]{2}[A-Z]{2}\\.nix" (lib.removePrefix "${product}." file) != null) variants));
  };
}) names)
