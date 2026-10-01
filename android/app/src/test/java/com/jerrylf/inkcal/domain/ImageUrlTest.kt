package com.jerrylf.inkcal.domain

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** 图片地址规则（docs/android-app-spec.md §8.4）。上游图片一律经服务端代理。 */
class ImageUrlTest {

  private val base = "http://your-server-host:5800/"

  @Test
  fun `缩略图把 original 换成 thumbnail，并去掉 base 的重复斜杠`() {
    val url =
      ImageUrl.thumbnail(
        base,
        "http://immich.local/api/assets/abc/original",
      )
    assertEquals(
      "http://your-server-host:5800/api/image?url=" +
        "http%3A%2F%2Fimmich.local%2Fapi%2Fassets%2Fabc%2Fthumbnail%3Fsize%3Dthumbnail",
      url,
    )
  }

  @Test
  fun `库里实际存的是 size=preview，也要降到 thumbnail`() {
    // 真实数据形态：http://your-immich-host:2283/api/assets/{id}/thumbnail?size=preview
    val url =
      ImageUrl.thumbnail(
        base,
        "http://your-immich-host:2283/api/assets/a5dff55e/thumbnail?size=preview",
      )
    assertTrue("必须降级成 thumbnail", url!!.contains("size%3Dthumbnail"))
    assertTrue("不能留在 preview", !url.contains("preview"))
  }

  @Test
  fun `已经是 thumbnail 的地址不再改动`() {
    assertEquals(
      "http://immich.local/api/assets/x/thumbnail?size=thumbnail",
      ImageUrl.smallVariant("http://immich.local/api/assets/x/thumbnail?size=thumbnail"),
    )
  }

  @Test
  fun `大图不替换 original`() {
    val url = ImageUrl.full(base, "http://immich.local/api/assets/abc/original")
    assertTrue(url!!.contains("abc%2Foriginal"))
    assertTrue(!url.contains("size=thumbnail"))
  }

  @Test
  fun `替换图优先走 local-image`() {
    val url = ImageUrl.thumbnail(base, "http://immich.local/x/original", "/data/uploads/a b.jpg")
    assertEquals(
      "http://your-server-host:5800/api/local-image?path=%2Fdata%2Fuploads%2Fa%20b.jpg",
      url,
    )
  }

  @Test
  fun `没图返回 null`() {
    assertNull(ImageUrl.thumbnail(base, ""))
    assertNull(ImageUrl.full(base, ""))
  }

  @Test
  fun `base 不带结尾斜杠也能拼`() {
    assertEquals(
      "http://host:5800/api/image?url=http%3A%2F%2Fu%2Foriginal",
      ImageUrl.full("http://host:5800", "http://u/original"),
    )
  }
}
