#!/bin/sh
# 构建 release APK 并发布到 GitHub Release。
#
#   android/release.sh            -> 只更新滚动 tag android-latest
#   android/release.sh v0.2       -> 建一个版本化的 release，同时把 android-latest 指向同一份包
#
# 滚动 tag 的 asset 每次覆盖，下载地址固定不变，手机存书签即可；版本化 tag 用来留档。
set -e
cd "$(dirname "$0")"

LATEST=android-latest
TAG="${1:-$LATEST}"
APK=app/build/outputs/apk/release/app-release.apk

./gradlew :app:assembleRelease

REPO=$(gh repo view --json nameWithOwner -q .nameWithOwner)
VERSION=$(sed -n 's/.*versionName *= *"\(.*\)".*/\1/p' app/build.gradle.kts | head -1)
BUILT=$(date '+%Y-%m-%d %H:%M')
SIZE=$(du -h "$APK" | cut -f1)

# 复制成固定文件名，asset 名（下载 URL 的最后一段）才稳定
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
cp "$APK" "$TMP/inkcal.apk"

# 每次构建都在自述里写明版本与时间，翻 release 列表时能对上
NOTES="inkcal $VERSION · 构建 $BUILT"

publish() {
  _tag="$1"
  if gh release view "$_tag" >/dev/null 2>&1; then
    gh release edit "$_tag" --notes "$NOTES" >/dev/null
  else
    gh release create "$_tag" --title "inkcal Android $_tag" --notes "$NOTES" --prerelease >/dev/null
  fi
  gh release upload "$_tag" "$TMP/inkcal.apk" --clobber >/dev/null
}

publish "$TAG"
echo "已发布 $TAG（$VERSION, $SIZE）"
echo "https://github.com/$REPO/releases/download/$TAG/inkcal.apk"

if [ "$TAG" != "$LATEST" ]; then
  # 版本化发布同时刷新滚动 tag，否则存了书签的地址会停在旧包上
  publish "$LATEST"
  echo "已同步 $LATEST（常驻下载地址）"
  echo "https://github.com/$REPO/releases/download/$LATEST/inkcal.apk"
fi
