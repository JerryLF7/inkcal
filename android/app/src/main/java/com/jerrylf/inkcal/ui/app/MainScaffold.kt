package com.jerrylf.inkcal.ui.app

import androidx.compose.animation.ContentTransform
import androidx.compose.animation.core.tween
import androidx.compose.animation.slideInHorizontally
import androidx.compose.animation.slideOutHorizontally
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.DateRange
import androidx.compose.material.icons.filled.Face
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.Icon
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.unit.IntOffset
import androidx.navigation3.runtime.NavKey
import androidx.navigation3.runtime.entryProvider
import androidx.navigation3.runtime.rememberNavBackStack
import androidx.navigation3.ui.NavDisplay
import com.jerrylf.inkcal.ui.calo.CaloScreen
import com.jerrylf.inkcal.ui.records.RecordsTab
import com.jerrylf.inkcal.ui.settings.SettingsScreen
import kotlinx.serialization.Serializable

@Serializable
data object RecordsRoute : NavKey

@Serializable
data object CaloRoute : NavKey

@Serializable
data object SettingsRoute : NavKey

/**
 * 三个一级 Tab。图标取自 material-icons-core（material3 不自带，见版本目录注释），
 * 只是占位级别的选择，等功能齐了再挑合适的。
 */
private enum class Tab(val route: NavKey, val label: String, val icon: ImageVector) {
  Records(RecordsRoute, "记录", Icons.Filled.DateRange),
  Calo(CaloRoute, "Calo", Icons.Filled.Face),
  Settings(SettingsRoute, "设置", Icons.Filled.Settings),
}

/**
 * Tab 间的滑动转场：forward = 点到了序号更大的 Tab，新页从右侧滑入、旧页向左退出；
 * 反之从左侧滑入、向右退出。就是"三页排成一行"的方向感。
 */
private fun tabSlide(forward: Boolean): ContentTransform {
  val spec = tween<IntOffset>(280)
  return if (forward) {
    slideInHorizontally(spec) { it } togetherWith slideOutHorizontally(spec) { -it }
  } else {
    slideInHorizontally(spec) { -it } togetherWith slideOutHorizontally(spec) { it }
  }
}

/**
 * 一级导航骨架：底部 Tab + Nav3。设置页不参与左右滑动（手指滑动还没做）。
 *
 * **方向要在点击处定，不能从 Nav3 的 `contentKey` 推**（2026-10-04 踩坑）：
 * `Scene.entries` 里的 entry 是被装饰器链重建过的，`contentKey` 不是我们的路由对象，
 * 拿它去比 Tab 下标恒得 -1/-1，方向就退化成永远同一个（真机表现：怎么切都朝一边滑）。
 * 所以这里只在 onClick 里记一个布尔，转场读它。
 */
@Composable
fun MainScaffold(viewModel: AppViewModel) {
  val backStack = rememberNavBackStack(RecordsRoute)

  // true = 往右切（序号变大）。初值只影响首帧，没有转场发生时不会被读到。
  var forward by remember { mutableStateOf(true) }

  Scaffold(
    bottomBar = {
      NavigationBar {
        val current = backStack.lastOrNull()
        val currentIndex = Tab.entries.indexOfFirst { it.route == current }
        Tab.entries.forEachIndexed { index, tab ->
          NavigationBarItem(
            selected = current == tab.route,
            onClick = {
              if (current != tab.route) {
                forward = index > currentIndex
                // 一级 Tab 之间不叠栈：切走就清空，返回键不会在 Tab 间来回跳
                backStack.clear()
                backStack.add(tab.route)
              }
            },
            icon = { Icon(tab.icon, contentDescription = null) },
            label = { Text(tab.label) },
          )
        }
      }
    },
  ) { inner ->
    NavDisplay(
      backStack = backStack,
      onBack = { backStack.removeLastOrNull() },
      modifier = Modifier.padding(inner),
      // NavDisplay 默认是渐入渐出，这里换成方向性滑动
      transitionSpec = { tabSlide(forward) },
      entryProvider =
        entryProvider {
          entry<RecordsRoute> { RecordsTab() }
          entry<CaloRoute> { CaloScreen() }
          entry<SettingsRoute> { SettingsScreen(appViewModel = viewModel) }
        },
    )
  }
}
