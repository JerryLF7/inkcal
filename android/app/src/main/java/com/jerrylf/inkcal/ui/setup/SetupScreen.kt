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
 * 首启向导：填服务器地址 → 需要时登录。两种形态共用一屏，由 [state] 决定。
 *
 * 地址与登录凭据只在这里使用；密码不落盘（只有会话 cookie 持久化）。
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

  val serverForm = state !is ConnState.NeedLogin || editingServer

  Column(
    modifier =
      Modifier.fillMaxSize()
        .safeDrawingPadding()
        .verticalScroll(rememberScrollState())
        .padding(24.dp),
    verticalArrangement = Arrangement.spacedBy(12.dp),
  ) {
    Text("inkcal", style = MaterialTheme.typography.headlineMedium)
    Text(
      if (serverForm) "填服务器地址（局域网 IP:端口 或反代域名）" else "登录后继续",
      style = MaterialTheme.typography.bodyMedium,
      color = MaterialTheme.colorScheme.onSurfaceVariant,
    )

    if (serverForm) {
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
      if (state is ConnState.NeedLogin) {
        TextButton(onClick = { viewModel.toggleServerForm() }) { Text("返回登录") }
      }
    } else {
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
      TextButton(onClick = { viewModel.toggleServerForm() }) { Text("修改服务器地址") }
    }

    if (state is ConnState.Failed) {
      Text(
        state.message,
        color = MaterialTheme.colorScheme.error,
        style = MaterialTheme.typography.bodyMedium,
      )
      TextButton(onClick = { viewModel.retry() }, enabled = !busy) { Text("重试") }
    }

    if (busy) LinearProgressIndicator(modifier = Modifier.fillMaxWidth())
  }
}
