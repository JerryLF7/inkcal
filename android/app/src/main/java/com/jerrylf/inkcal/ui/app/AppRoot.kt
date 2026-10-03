package com.jerrylf.inkcal.ui.app

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.lifecycle.compose.LifecycleStartEffect
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.jerrylf.inkcal.data.ConnState
import com.jerrylf.inkcal.ui.setup.SetupScreen
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

/** §8.6：前台每 30 秒问一次数据版本。 */
private const val POLL_INTERVAL_MS = 30_000L

/**
 * 顶层分流：连不上服务器就进设置向导，连上才显示三个 Tab。
 *
 * 登录页刻意不做成第四个 Tab——它只在需要时挡住整个 App。
 */
@Composable
fun AppRoot(viewModel: AppViewModel = viewModel()) {
  val state by viewModel.state.collectAsStateWithLifecycle()

  // 放在这一层而不是记录页里：切到 Calo / 设置时也要继续同步
  if (state is ConnState.Ready) DataVersionWatcher(viewModel)

  when (val current = state) {
    ConnState.Loading ->
      Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        CircularProgressIndicator()
      }

    is ConnState.Ready -> MainScaffold(version = current.version, viewModel = viewModel)

    else -> SetupScreen(state = current, viewModel = viewModel)
  }
}

/**
 * cron 会在后台写记录，前端只负责发现「变了」。
 *
 * 用 [LifecycleStartEffect]（`repeatOnLifecycle(STARTED)` 的 Compose 版本）：进后台停、
 * 回前台立即轮询一次，不引前台服务或 WorkManager。网络失败静默——这是增强项，
 * 不该因为断网弹任何东西给用户。
 *
 * 版本基线与比对都在 [AppViewModel.checkDataVersion] 里，这里只管按节拍调用。
 */
@Composable
private fun DataVersionWatcher(viewModel: AppViewModel) {
  val scope = rememberCoroutineScope()

  LifecycleStartEffect(Unit) {
    val job =
      scope.launch {
        while (true) {
          viewModel.checkDataVersion()
          delay(POLL_INTERVAL_MS)
        }
      }
    onStopOrDispose { job.cancel() }
  }
}
