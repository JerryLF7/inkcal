package com.jerrylf.inkcal.domain

import java.net.URLEncoder

/**
 * 图片地址规则（docs/android-app-spec.md §8.4）。上游图片一律经服务端代理，
 * 客户端不直连 Immich/PhotoPrism。
 *
 * base 是规范化过的服务器地址（**以 `/` 结尾**），拼路径时要先去掉那个斜杠，
 * 否则会拼出 `//api/image`。
 */
object ImageUrl {

  private fun endpoint(base: String, path: String): String = base.trimEnd('/') + path

  private fun enc(raw: String): String =
    URLEncoder.encode(raw, "UTF-8").replace("+", "%20")

  /** 卡片缩略图：把上游 URL 降级成 thumbnail（约 7KB，别用约 157KB 的 preview）。 */
  fun thumbnail(base: String, thumbnailUrl: String, replacementImage: String = ""): String? {
    if (replacementImage.isNotBlank()) return local(base, replacementImage)
    if (thumbnailUrl.isBlank()) return null
    return endpoint(base, "/api/image?url=${enc(smallVariant(thumbnailUrl))}")
  }

  /**
   * Immich 的成图有两种形态，都要降到 thumbnail：
   *   .../assets/{id}/original            -> .../assets/{id}/thumbnail?size=thumbnail
   *   .../assets/{id}/thumbnail?size=preview -> ...?size=thumbnail
   *
   * 只做 `/original` 那一半的替换在真实数据上是空操作——库里存的本来就是
   * `?size=preview`，卡片会去拉 157KB 的图（网页版目前就是这样）。
   */
  internal fun smallVariant(url: String): String =
    when {
      url.contains("/original") -> url.replace("/original", "/thumbnail?size=thumbnail")
      url.contains("size=preview") -> url.replace("size=preview", "size=thumbnail")
      else -> url
    }

  /** 详情大图：用原始 url，不做替换。 */
  fun full(base: String, thumbnailUrl: String, replacementImage: String = ""): String? {
    if (replacementImage.isNotBlank()) return local(base, replacementImage)
    if (thumbnailUrl.isBlank()) return null
    return endpoint(base, "/api/image?url=${enc(thumbnailUrl)}")
  }

  private fun local(base: String, path: String): String =
    endpoint(base, "/api/local-image?path=${enc(path)}")
}
