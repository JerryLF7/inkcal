package com.jerrylf.inkcal.ui.setup

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.jerrylf.inkcal.data.ConnState
import com.jerrylf.inkcal.ui.app.AppViewModel

/**
 * 启动连接页：按状态分为三种明确形态，不再在已配好服务器却瞬时断网时把用户踢回「填地址表单」：
 * 1. 未配地址或用户主动点「修改服务器地址」→ 服务器地址输入表单；
 * 2. 服务端要求登录（401）→ 账号密码表单；
 * 3. 已配地址但暂时连不上（[ConnState.Failed]）→ 简洁的重试页（主按钮「重试」，副按钮「修改服务器地址」）。
 */
@Composable
fun SetupScreen(state: ConnState, viewModel: AppViewModel) {
  val baseUrl by viewModel.baseUrl.collectAsStateWithLifecycle()
  val busy by viewModel.busy.collectAsStateWithLifecycle()
  val editingServer by viewModel.showServerForm.collectAsStateWithLifecycle()

  var urlInput by rememberSaveable { mutableStateOf("") }
  var user by rememberSaveable { mutableStateOf("") }
  var password by rememberSaveable { mutableStateOf("") }

  LaunchedEffect(baseUrl) { if (urlInput.isBlank()) urlInput = baseUrl }

  val showServerInput = state is ConnState.NeedServer || baseUrl.isBlank() || editingServer
  val showLoginForm = !showServerInput && state is ConnState.NeedLogin

  Column(
    modifier =
      Modifier.fillMaxSize()
        .safeDrawingPadding()
        .verticalScroll(rememberScrollState())
        .padding(24.dp),
    verticalArrangement = Arrangement.spacedBy(12.dp),
  ) {
    Text("inkcal", style = MaterialTheme.typography.headlineMedium)

    when {
      showServerInput -> {
        Text(
          "填服务器地址（局域网 IP:端口 或反代域名）",
          style = MaterialTheme.typography.bodyMedium,
          color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        OutlinedTextField(
          value = urlInput,
          onValueChange = { urlInput = it },
          label = { Text("服务器地址") },
          placeholder = { Text("https://inkcal.example.com") },
          singleLine = true,
          keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri),
          modifier = Modifier.fillMaxWidth(),
        )
        Button(
          onClick = { viewModel.saveServer(urlInput) },
          enabled = !busy && urlInput.isNotBlank(),
          modifier = Modifier.fillMaxWidth(),
        ) {
          Text("保存并连接")
        }
        if (editingServer && baseUrl.isNotBlank()) {
          TextButton(onClick = { viewModel.toggleServerForm() }, enabled = !busy) {
            Text(if (state is ConnState.NeedLogin) "返回登录" else "返回")
          }
        }
        if (state is ConnState.Failed) {
          Text(
            state.message,
            color = MaterialTheme.colorScheme.error,
            style = MaterialTheme.typography.bodyMedium,
          )
        }
      }

      showLoginForm -> {
        Text(
          "登录后继续",
          style = MaterialTheme.typography.bodyMedium,
          color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        OutlinedTextField(
          value = user,
          onValueChange = { user = it },
          label = { Text("用户名") },
          singleLine = true,
          modifier = Modifier.fillMaxWidth(),
        )
        OutlinedTextField(
          value = password,
          onValueChange = { password = it },
          label = { Text("密码") },
          singleLine = true,
          visualTransformation = PasswordVisualTransformation(),
          keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
          modifier = Modifier.fillMaxWidth(),
        )
        Button(
          onClick = { viewModel.login(user, password) },
          enabled = !busy && user.isNotBlank() && password.isNotBlank(),
          modifier = Modifier.fillMaxWidth(),
        ) {
          Text("登录")
        }
        TextButton(onClick = { viewModel.toggleServerForm() }, enabled = !busy) {
          Text("修改服务器地址")
        }
      }

      else -> {
        // 已保存服务器地址但瞬时连接失败：默认给「重试」，不把人踢回首启填地址页
        Text(
          "暂时无法连接服务器",
          style = MaterialTheme.typography.bodyMedium,
          color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Text(
          baseUrl.trimEnd('/'),
          style = MaterialTheme.typography.bodySmall,
          color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        if (state is ConnState.Failed) {
          Text(
            state.message,
            color = MaterialTheme.colorScheme.error,
            style = MaterialTheme.typography.bodyMedium,
          )
        }
        Button(
          onClick = { viewModel.retry() },
          enabled = !busy,
          modifier = Modifier.fillMaxWidth(),
        ) {
          Text("重试")
        }
        TextButton(onClick = { viewModel.toggleServerForm() }, enabled = !busy) {
          Text("修改服务器地址")
        }
      }
    }

    if (busy) LinearProgressIndicator(modifier = Modifier.fillMaxWidth())
  }
}
