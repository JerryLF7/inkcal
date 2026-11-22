package com.jerrylf.inkcal.domain

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class PredictiveBackMathTest {

  private val density = 3f
  private val widthPx = 412f * density // 常见手机宽 412dp
  private val heightPx = 915f * density // 常见手机高 915dp

  @Test
  fun `preCommit keeps foreground fully opaque throughout gesture`() {
    listOf(0f, 0.1f, 0.44f, 0.75f, 1f).forEach { p ->
      val v = PredictiveBackMath.preCommit(p, BackSwipeEdge.LEFT, 0f, widthPx, heightPx, density)
      assertEquals("alpha must stay 1.0 during pre-commit (p=$p)", 1f, v.fgAlpha, 1e-4f)
    }
  }

  @Test
  fun `preCommit scales to 0_90 and leaves 8dp opposite margin at full progress`() {
    val left = PredictiveBackMath.preCommit(1f, BackSwipeEdge.LEFT, 0f, widthPx, heightPx, density)
    assertEquals(0.90f, left.fgScale, 1e-4f)
    // 右侧边距 = (width * 0.05) - translationX = 8dp * density
    val rightGapPx = widthPx * 0.05f - left.fgTranslationX
    assertEquals(8f * density, rightGapPx, 1e-2f)
    assertTrue("left swipe shifts right (+X)", left.fgTranslationX > 0f)

    val right = PredictiveBackMath.preCommit(1f, BackSwipeEdge.RIGHT, 0f, widthPx, heightPx, density)
    assertEquals(0.90f, right.fgScale, 1e-4f)
    assertEquals(-left.fgTranslationX, right.fgTranslationX, 1e-2f)
    assertTrue("right swipe shifts left (-X)", right.fgTranslationX < 0f)
  }

  @Test
  fun `preCommit follows vertical touch delta with clamping and returns to zero at progress 0`() {
    val down = PredictiveBackMath.preCommit(1f, BackSwipeEdge.LEFT, 300f, widthPx, heightPx, density)
    val up = PredictiveBackMath.preCommit(1f, BackSwipeEdge.LEFT, -300f, widthPx, heightPx, density)
    assertTrue(down.fgTranslationY > 0f)
    assertEquals(-down.fgTranslationY, up.fgTranslationY, 1e-2f)

    val huge = PredictiveBackMath.preCommit(1f, BackSwipeEdge.LEFT, 50_000f, widthPx, heightPx, density)
    assertTrue(huge.fgTranslationY <= PredictiveBackMath.MAX_VERTICAL_SHIFT_DP * density + 1e-2f)

    val idle = PredictiveBackMath.preCommit(0f, BackSwipeEdge.LEFT, 300f, widthPx, heightPx, density)
    assertEquals(0f, idle.fgTranslationY, 1e-4f)
    assertEquals(0f, idle.fgCornerRadiusDp, 1e-4f)
  }

  @Test
  fun `postCommit continues in the SAME direction as swipe edge with zero discontinuity`() {
    for (edge in BackSwipeEdge.entries) {
      val snapshot =
        PredictiveBackMath.preCommit(0.45f, edge, 120f, widthPx, heightPx, density)
      val start = PredictiveBackMath.postCommit(0f, snapshot, edge, density)
      assertEquals(snapshot.fgScale, start.fgScale, 1e-4f)
      assertEquals(snapshot.fgTranslationX, start.fgTranslationX, 1e-4f)
      assertEquals(snapshot.fgTranslationY, start.fgTranslationY, 1e-4f)
      assertEquals(snapshot.fgAlpha, start.fgAlpha, 1e-4f)
      assertEquals(snapshot.bgTranslationX, start.bgTranslationX, 1e-4f)
      assertEquals(snapshot.scrimAlpha, start.scrimAlpha, 1e-4f)

      val end = PredictiveBackMath.postCommit(1f, snapshot, edge, density)
      if (edge == BackSwipeEdge.LEFT) {
        assertTrue("left swipe must keep moving right", end.fgTranslationX > start.fgTranslationX)
      } else {
        assertTrue("right swipe must keep moving left", end.fgTranslationX < start.fgTranslationX)
      }
      assertEquals(0f, end.fgAlpha, 1e-4f)
      assertEquals(1f, end.bgScale, 1e-4f)
      assertEquals(0f, end.bgTranslationX, 1e-4f)
      assertEquals(0f, end.scrimAlpha, 1e-4f)
    }
  }

  @Test
  fun `postCommit stays visible during early release and fades smoothly across middle frames`() {
    val snapshot =
      PredictiveBackMath.preCommit(0.5f, BackSwipeEdge.LEFT, 0f, widthPx, heightPx, density)

    // 约 38ms（12% 线性时间）时仍在加速滑出，前景必须保持完全可见，绝不 2 帧闪没（0.28 回归护栏）
    val early = PredictiveBackMath.postCommit(0.12f, snapshot, BackSwipeEdge.LEFT, density)
    assertEquals(1f, early.fgAlpha, 1e-4f)
    assertTrue("card should already be gliding outward", early.fgTranslationX > snapshot.fgTranslationX)

    // 约 128ms（40% 线性时间）时处于柔和半透明过渡区
    val mid = PredictiveBackMath.postCommit(0.40f, snapshot, BackSwipeEdge.LEFT, density)
    assertTrue("mid-exit alpha should be visibly transitioning (was ${mid.fgAlpha})", mid.fgAlpha in 0.35f..0.70f)

    // 约 240ms（75% 线性时间）后前景完全淡出，底页仍在平滑收尾
    val late = PredictiveBackMath.postCommit(0.75f, snapshot, BackSwipeEdge.LEFT, density)
    assertEquals(0f, late.fgAlpha, 1e-4f)
    assertTrue("background should still be finishing settle", late.bgTranslationX < 0f)
    assertTrue("scrim should still be finishing fade", late.scrimAlpha > 0f)
  }

  @Test
  fun `enter animation starts shifted right and settles to identity`() {
    val start = PredictiveBackMath.enter(0f, density)
    assertEquals(0f, start.fgAlpha, 1e-4f)
    assertTrue(start.fgTranslationX > 0f)
    assertEquals(1f, start.bgScale, 1e-4f)
    assertEquals(0f, start.bgTranslationX, 1e-4f)

    val end = PredictiveBackMath.enter(1f, density)
    assertEquals(1f, end.fgAlpha, 1e-4f)
    assertEquals(0f, end.fgTranslationX, 1e-4f)
    assertEquals(1f, end.fgScale, 1e-4f)
    assertEquals(PredictiveBackMath.MAX_SCRIM_ALPHA, end.scrimAlpha, 1e-4f)
  }
}
