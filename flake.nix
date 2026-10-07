{
  description = "Pinned NGDP/TACT installations and isolated Battle.net game runtimes";
  inputs.nixpkgs.url = "github:nixos/nixpkgs/nixos-unstable";
  outputs = { self, nixpkgs }:
    let
      systems = [ "x86_64-linux" "aarch64-darwin" ];
      forSystems = nixpkgs.lib.genAttrs systems;
      packagesFor = system:
        let
          # These packages are explicitly requested proprietary game installations.
          # Consumers of the overlay retain their own nixpkgs license policy.
          pkgs = import nixpkgs { inherit system; config.allowUnfree = true; };
          api = pkgs.callPackage ./default.nix {};
          catalog = import ./profiles.nix { inherit system; inherit (pkgs) lib; };
          complete = pkgs.lib.filterAttrs (_: game: game ? installation) catalog;
          gameSettings = pkgs.lib.mapAttrs' (product: game:
            pkgs.lib.nameValuePair product {
              inherit (game) release installation;
              inherit (game.installation) executable args;
            }) complete;
        in api.mkGames gameSettings;
    in {
      overlays.default = import ./overlay.nix;
      nixosModules.default = import ./module.nix;
      darwinModules.default = import ./module.nix;
      lib.mkGames = { pkgs, games }: (pkgs.callPackage ./default.nix {}).mkGames games;
      packages = forSystems packagesFor;
      devShells = forSystems (system:
        let pkgs = import nixpkgs { inherit system; };
        in { ci = pkgs.mkShellNoCC {
          packages = [ pkgs.python3 pkgs.nushell pkgs.git pkgs.nix pkgs.gh pkgs.gnutar pkgs.gzip ];
        }; });
    };
}
