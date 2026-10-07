{ config, lib, pkgs, ... }:
let
  inherit (lib) mkEnableOption mkOption types;
  cfg = config.programs.battlenet;
  api = pkgs.battlenet;
  catalog = import ./profiles.nix { inherit lib; system = pkgs.stdenv.hostPlatform.system; };
in {
  options.programs.battlenet = {
    enable = mkEnableOption "declarative Battle.net games";
    games = mkOption {
      default = {};
      description = "Configure games by product code and enable each explicitly; bundled native Nix records supply installation and launch defaults.";
      type = types.attrsOf (types.submodule ({ name, config, ... }: let
        profile = catalog.${name} or {};
        selected = if !config.enable || config.content != null then profile else
          (import ./select-profile.nix { inherit lib; }) profile config.locale config.region;
        installation = selected.installation or {};
      in {
        options = {
          enable = mkEnableOption "Battle.net game ${name}";
          locale = mkOption {
            type = types.nullOr (types.strMatching "[a-z]{2}[A-Z]{2}");
            default = if config.region == "cn" then "zhCN" else null;
            description = "Game language; selects a verified installation and manages known client preferences where supported. China defaults to zhCN assets. Null uses the bundled installation without managing language preferences.";
          };
          region = mkOption {
            type = types.nullOr types.str;
            default = null;
            description = "China selects a separate verified distribution and isolated state; authentication uses that client's login flow. WoW additionally manages the us/eu/cn portal preference; null leaves service preferences unchanged.";
          };
          release = mkOption ({ type = types.attrs; description = "Pinned release data; defaults to the bundled game record."; }
            // lib.optionalAttrs (selected ? release) { default = selected.release; });
          installation = mkOption {
            type = types.nullOr types.attrs;
            default = if config.content != null then null else selected.installation or null;
            description = "Complete installation data with storage records and final hash; alternative to content.";
          };
          content = mkOption { type = types.nullOr types.package; default = null; description = "Custom immutable game tree; overrides the bundled installation source."; };
          executable = mkOption ({ type = types.str; description = "Relative game executable path; macOS uses a native app bundle executable."; }
            // lib.optionalAttrs (installation ? executable) { default = installation.executable; });
          args = mkOption { type = types.listOf types.str; default = installation.args or []; };
          persistentDirectories = mkOption {
            type = types.nullOr (types.listOf types.str);
            default = null;
            description = "User directories relative to the game root to retain between launches; null selects game defaults.";
          };
        };
      }));
    };
  };
  config = lib.mkIf cfg.enable ({
    nixpkgs.overlays = [ (import ./overlay.nix) ];
    environment.systemPackages = lib.attrValues (api.mkGames (
      lib.mapAttrs (_: game: builtins.removeAttrs game [ "enable" ])
        (lib.filterAttrs (_: game: game.enable) cfg.games)
    ));
  } // lib.optionalAttrs pkgs.stdenv.hostPlatform.isLinux {
    # Per-object inputs can exceed Linux's default sandbox mount limit.
    boot.kernel.sysctl."fs.mount-max" = lib.mkDefault 2000000;
  });
}
