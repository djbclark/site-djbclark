# The tendcf CFEngine fork (https://github.com/djbclark/core, branch tendcf-integration),
# built from source at the exact commit tendcf pins in overlay/fork.json. nixpkgs has no
# cfengine package, so this is not an override.
#
# Two things differ from a plain `./autogen.sh && make`:
#  - The fork's libntech submodule commit exists only on https://github.com/djbclark/libntech
#    (not on the upstream .gitmodules URL), so the core is fetched without submodules and
#    libntech is fetched separately and copied into libntech/.
#  - The version string `cf-agent --version` prints (CFEngine Core 3.29.0a.<9-char commit>)
#    normally comes from misc/determine-version.sh via git, and a Nix source has no .git.
#    autogen.sh writes that string to CFVERSION, which configure.ac reads; we write the same
#    file ourselves.
{
  lib,
  stdenv,
  fetchFromGitHub,
  autoreconfHook,
  pkg-config,
  bison,
  flex,
  libtool,
  openssl,
  pcre2,
  lmdb,
  libyaml,
  libxml2,
  librsync,
  acl,
  pam,
}:

let
  rev = "b8abf28408b1b54e285d372a9bc5f2d850c960ad";
  # determine-version.sh: `cut -b 1-9` of HEAD.
  shortRev = builtins.substring 0 9 rev;
  baseVersion = "3.29.0"; # .CFVERSION at this commit
  # Compiled in (--with-workdir); nixos/modules/cfengine-tendcf.nix reads it back from here.
  workdir = "/var/lib/cfengine-tendcf";

  # The submodule pointer of the commit above.
  libntech = fetchFromGitHub {
    owner = "djbclark";
    repo = "libntech";
    rev = "d379dce2cf79c4b95112cce482797e93ddcad5dc";
    hash = "sha256-XxHIzsLzIPvXPZVO5Pk3+Rlxb7g7NMuHHFDHz5soU+0=";
  };
in
stdenv.mkDerivation {
  pname = "cfengine-tendcf";
  version = "${baseVersion}a.${shortRev}";

  src = fetchFromGitHub {
    owner = "djbclark";
    repo = "core";
    inherit rev;
    hash = "sha256-F6pK5Nmog/MgTRoqPy/J8NBFWeiXOSdj3fgleGHqnZg=";
  };

  postPatch = ''
    mkdir -p libntech
    cp -r ${libntech}/. libntech/
    chmod -R u+w libntech
    echo "${baseVersion}a.${shortRev}" > CFVERSION
    cp CFVERSION libntech/CFVERSION
  '';

  nativeBuildInputs = [
    autoreconfHook
    pkg-config
    bison
    flex
    libtool
  ];

  buildInputs = [
    openssl
    pcre2
    lmdb
    libyaml
    libxml2
    librsync
    acl
    pam
  ];

  # autogen.sh runs `autoreconf -Wno-portability --force --install -I m4`; the -I m4 comes
  # from ACLOCAL_AMFLAGS, and autoreconf recurses into libntech (AC_CONFIG_SUBDIRS).
  autoreconfFlags = "--install --force --verbose -Wno-portability";

  # No --with-<lib>=PATH: CFEngine's CF3_WITH_LIBRARY turns PATH into -I$PATH/include
  # -L$PATH/lib -R$PATH/lib, which is wrong for nixpkgs' split dev/out outputs. The stdenv
  # wrapper already puts every buildInput on the include and link paths. `=yes` makes the
  # optional ones (default `check`) mandatory so a missing library fails configure loudly;
  # lmdb, openssl, pcre2 and librsync are mandatory by default, PAM is required on linux-gnu.
  configureFlags = [
    "--with-workdir=${workdir}"
    "--with-systemd-service=no"
    "--with-libacl=yes"
    "--with-libyaml=yes"
    "--with-libxml2=yes"
    "--with-pam=yes"
  ];

  # `make install` mkdirs $(workdir)/{inputs,modules,...} (install-data-local, in the core and
  # in libntech); that is /var/lib/... inside the build sandbox. The module's tmpfiles rule
  # owns the real directory, so aim the hook at a scratch path. workdir is a Makefile-only
  # variable here: the compiled-in WORKDIR (config.h) is unaffected.
  installFlags = [ "workdir=$(NIX_BUILD_TOP)/discarded-workdir" ];

  enableParallelBuilding = true;

  passthru = { inherit workdir; };

  meta = {
    description = "CFEngine core, tendcf fork (binaries only; work directory is ${workdir})";
    homepage = "https://github.com/djbclark/core/tree/tendcf-integration";
    license = lib.licenses.gpl3Only;
    platforms = lib.platforms.linux;
    mainProgram = "cf-agent";
  };
}
