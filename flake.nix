{
  description = "MediaHarvester: скачивает видео, музыку и фото из соцсетей (YouTube, VK, Instagram, TikTok, X и другие)";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs = { self, nixpkgs }:
    let
      systems = [ "x86_64-linux" "aarch64-linux" ];
      forAllSystems = f: nixpkgs.lib.genAttrs systems (system: f nixpkgs.legacyPackages.${system});
    in
    {
      packages = forAllSystems (pkgs: rec {
        mediaharvester = pkgs.callPackage ./packaging/nix/package.nix { };
        default = mediaharvester;
      });

      apps = forAllSystems (pkgs: {
        default = {
          type = "app";
          program = "${self.packages.${pkgs.stdenv.hostPlatform.system}.default}/bin/mediaharvester";
        };
      });

      # Для configuration.nix: nixpkgs.overlays = [ mediaharvester.overlays.default ];
      overlays.default = final: _prev: {
        mediaharvester = final.callPackage ./packaging/nix/package.nix { };
      };
    };
}
