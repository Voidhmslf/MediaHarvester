# Сборка MediaHarvester из исходников для Nix.
# Отличия от AppImage: ffmpeg и yt-dlp берутся из nixpkgs и обновляются вместе с системой,
# поэтому самообновление yt-dlp выключено (MH_NO_SELF_UPDATE), а путь к ffmpeg задаёт обёртка (MH_FFMPEG).
{
  lib,
  stdenvNoCC,
  python3,
  fetchPypi,
  gallery-dl,
  ffmpeg,
  makeWrapper,
}:

let
  root = ../..;

  version = builtins.head (
    builtins.match ''.*__version__ = "([^"]+)".*'' (builtins.readFile (root + "/src/version.py"))
  );

  # vk_api и vkpymusic в nixpkgs нет — берём готовые wheel с PyPI
  vk-api =
    ps:
    ps.buildPythonPackage rec {
      pname = "vk_api";
      version = "11.10.1";
      format = "wheel";
      src = fetchPypi {
        inherit pname version format;
        dist = "py3";
        python = "py3";
        hash = "sha256-iV1bnl9xVkQ6W1DQmsA8hSen9utkyVlI+brr+f1Wjng=";
      };
      dependencies = [ ps.requests ];
      pythonImportsCheck = [ "vk_api" ];
    };

  vkpymusic =
    ps:
    ps.buildPythonPackage rec {
      pname = "vkpymusic";
      version = "4.0.2";
      format = "wheel";
      src = fetchPypi {
        inherit pname version format;
        dist = "py3";
        python = "py3";
        hash = "sha256-cKYhVrXaxsZ/XlrxMpdZdWT0RqVlterwoGd66E4sWHI=";
      };
      dependencies = with ps; [
        aiofiles
        av
        cryptography
        curl-cffi
        requests
        selenium
        webdriver-manager
      ];
      # Верхние границы версий в метаданных слишком строгие для nixpkgs
      pythonRelaxDeps = true;
      pythonImportsCheck = [ "vkpymusic" ];
    };

  python = python3.withPackages (
    ps: with ps; [
      tkinter
      customtkinter
      pillow
      requests
      yt-dlp
      mutagen
      (vk-api ps)
      (vkpymusic ps)
      # gallery-dl в nixpkgs — программа, а не библиотека; программа запускает его через `python -m gallery_dl`
      (toPythonModule gallery-dl)
    ]
  );
in
stdenvNoCC.mkDerivation {
  pname = "mediaharvester";
  inherit version;

  # Только то, что нужно программе: без android/, тестов и сборок
  src = lib.fileset.toSource {
    inherit root;
    fileset = lib.fileset.unions [
      (root + "/main.py")
      (root + "/src")
      (root + "/assets")
      (root + "/packaging/linux/mediaharvester.desktop")
      (root + "/MediaHarvester-brand/linux/hicolor")
    ];
  };

  nativeBuildInputs = [ makeWrapper ];

  dontBuild = true;

  installPhase = ''
    runHook preInstall

    mkdir -p $out/share/mediaharvester $out/share/applications $out/share/icons
    cp -r main.py src assets $out/share/mediaharvester/
    find $out/share/mediaharvester -name '__pycache__' -type d -prune -exec rm -rf {} +

    makeWrapper ${python.interpreter} $out/bin/mediaharvester \
      --add-flags $out/share/mediaharvester/main.py \
      --set MH_FFMPEG ${lib.getExe ffmpeg} \
      --set MH_NO_SELF_UPDATE 1

    sed "s|@EXEC@|mediaharvester|" packaging/linux/mediaharvester.desktop \
      > $out/share/applications/mediaharvester.desktop
    cp -r MediaHarvester-brand/linux/hicolor $out/share/icons/

    runHook postInstall
  '';

  meta = {
    description = "Downloads video, music and photos from YouTube, VK, Instagram, TikTok, X and other sites";
    homepage = "https://github.com/Voidhmslf/MediaHarvester";
    changelog = "https://github.com/Voidhmslf/MediaHarvester/blob/main/CHANGELOG.md";
    license = lib.licenses.mit;
    mainProgram = "mediaharvester";
    platforms = lib.platforms.linux;
  };
}
