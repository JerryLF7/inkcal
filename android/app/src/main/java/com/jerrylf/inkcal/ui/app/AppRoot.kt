package com.jerrylf.inkcal.ui.app

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.jerrylf.inkcal.data.ConnState
import com.jerrylf.inkcal.ui.setup.SetupScreen

/**
 * 顶层分流：连不上服务器就进设置向导，连上才显示三个 Tab。
 *
 * 登录页刻意不做成第四个 Tab——它只在需要时挡住整个 App。
 */
@Composable
fun AppRoot(viewModel: AppViewModel = viewModel()) {
  val state by viewModel.state.collectAsStateWithLifecycle()

  when (val current = state) {
    ConnState.Loading ->
      Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        CircularProgressIndicator()
      }

    is ConnState.Ready -> MainScaffold(version = current.version, viewModel = viewModel)

    else -> SetupScreen(state = current, viewModel = viewModel)
  }
}
