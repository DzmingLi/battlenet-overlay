# Keep release/language selection local; fetch the full pinned object graph only
# when an installation actually needs its objects, indexes or loose files.
{ game, url, hash }:
let
  full = import (builtins.fetchTarball { inherit url; sha256 = hash; } + "/catalog.nix");
in game // {
  installation = game.installation // {
    storage = game.installation.storage // {
      bootstrap = full.installation.storage.bootstrap;
      objects = full.installation.storage.objects;
      installFiles = full.installation.storage.installFiles;
    };
  };
}
