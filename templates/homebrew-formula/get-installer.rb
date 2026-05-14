# Homebrew formula for `get-installer`.
#
# This file is the live formula that ships in the `simtabi/homebrew-tap`
# repository at `Formula/get-installer.rb`. The release workflow keeps
# `url` and `sha256` in sync with each PyPI release; everything else is
# stable.
#
# Tap usage:
#   brew tap simtabi/tap
#   brew install get-installer
#
# Or one-shot:
#   brew install simtabi/tap/get-installer
#
# To regenerate locally after a PyPI release (X.Y.Z):
#   brew create --python --tap simtabi/tap \
#     https://files.pythonhosted.org/packages/source/g/get-installer/get_installer-X.Y.Z.tar.gz
#   brew update-python-resources Formula/get-installer.rb
#   brew style --fix Formula/get-installer.rb
#   brew audit --new --strict Formula/get-installer.rb
#
# get-installer has zero runtime dependencies (stdlib only), so no
# `resource` blocks are required. The depends_on line is just Python.

class GetInstaller < Formula
  include Language::Python::Virtualenv

  desc "Registry-driven curl-pipe-sh-style installer for dev tools"
  homepage "https://opensource.simtabi.com/products/get-installer"
  url "https://files.pythonhosted.org/packages/source/g/get-installer/get_installer-0.2.0.tar.gz"
  sha256 "REPLACE_WITH_PYPI_SDIST_SHA256_ON_RELEASE"
  license "MIT"
  head "https://github.com/simtabi/get-installer.git", branch: "main"

  depends_on "python@3.13"

  def install
    virtualenv_install_with_resources
  end

  test do
    # The CLI must accept --version. Catches a virtualenv that built
    # but has no working entry point.
    assert_match version.to_s, shell_output("#{bin}/get-installer --version")

    # --list prints the registry catalog header; passes against the
    # default registry baked into the wheel.
    assert_match "Available products", shell_output("#{bin}/get-installer --list")

    # --dry-run on a non-existent product fails cleanly; catches an
    # installer that silently no-ops.
    output = shell_output("#{bin}/get-installer --product no-such --dry-run --yes 2>&1", 1)
    assert_match "unknown product", output.downcase
  end
end
