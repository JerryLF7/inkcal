#!/bin/sh
# 构建 release APK 并发布到 GitHub Release。
#
#   android/release.sh          -> tag 取 app/build.gradle.kts 里的 versionName，例如 v0.1
#   android/release.sh v0.2     -> 显式指定 tag
#
# 约定：tag 与 asset 名都带版本号（v0.1 / inkcal-0.1.apk），release 不标 pre-release，
# 这样 GitHub 会把它算作 Latest release，仓库首页侧栏才会显示。
# 固定入口用 GitHub 自带的重定向，永远指向最新正式版：
#   https://github.com/<owner>/<repo>/releases/latest
set -e
cd "$(dirname "$0")"

APK=app/build/outputs/apk/release/app-release.apk

./gradlew :app:assembleRelease

REPO=$(gh repo view --json nameWithOwner -q .nameWithOwner)
VERSION=$(sed -n 's/.*versionName *= *"\(.*\)".*/\1/p' app/build.gradle.kts | head -1)
[ -n "$VERSION" ] || { echo "读不到 versionName，检查 app/build.gradle.kts" >&2; exit 1; }
TAG="${1:-v$VERSION}"
BUILT=$(date '+%Y-%m-%d %H:%M')
SIZE=$(du -h "$APK" | cut -f1)
ASSET="inkcal-$VERSION.apk"
NOTES="inkcal $VERSION · 构建 $BUILT"

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
cp "$APK" "$TMP/$ASSET"

if gh release view "$TAG" >/dev/null 2>&1; then
  gh release edit "$TAG" --title "inkcal Android $VERSION" --notes "$NOTES" --prerelease=false >/dev/null
else
  # 不传 --prerelease，GitHub 才会把它标成 Latest release
  gh release create "$TAG" --title "inkcal Android $VERSION" --notes "$NOTES" >/dev/null
fi
gh release upload "$TAG" "$TMP/$ASSET" --clobber >/dev/null

echo "已发布 $TAG（$VERSION, $SIZE）"
echo "https://github.com/$REPO/releases/download/$TAG/$ASSET"
echo "固定入口 https://github.com/$REPO/releases/latest"
