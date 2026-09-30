#!/bin/sh
# 构建 release APK 并发布到 GitHub Release 的滚动 tag（默认 android-latest）。
# 每次发布覆盖同一个 asset，所以下载地址固定不变，手机存书签即可。
#
# 用法：android/release.sh [tag]
set -e
cd "$(dirname "$0")"

TAG="${1:-android-latest}"
APK=app/build/outputs/apk/release/app-release.apk

./gradlew :app:assembleRelease

REPO=$(gh repo view --json nameWithOwner -q .nameWithOwner)
VERSION=$(sed -n 's/.*versionName *= *"\(.*\)".*/\1/p' app/build.gradle.kts | head -1)
BUILT=$(date '+%Y-%m-%d %H:%M')
SIZE=$(du -h "$APK" | cut -f1)

if gh release view "$TAG" >/dev/null 2>&1; then
  gh release edit "$TAG" --notes "inkcal $VERSION · 构建 $BUILT"
else
  gh release create "$TAG" \
    --title "inkcal Android 最新构建" \
    --notes "inkcal $VERSION · 构建 $BUILT" \
    --prerelease
fi

# 复制成固定文件名，asset 名（也是下载 URL 的最后一段）才稳定
TMP=$(mktemp -d)
cp "$APK" "$TMP/inkcal.apk"
gh release upload "$TAG" "$TMP/inkcal.apk" --clobber
rm -rf "$TMP"

echo "已发布 $VERSION ($SIZE)"
echo "https://github.com/$REPO/releases/download/$TAG/inkcal.apk"
