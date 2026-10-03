package com.jerrylf.inkcal.ui.app

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.jerrylf.inkcal.data.AppContainer
import com.jerrylf.inkcal.data.ConnState
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

/**
 * App 级状态：服务器地址与登录状态。会话内只有一个实例（挂在 Activity 上）。
 */
class AppViewModel(app: Application) : AndroidViewModel(app) {

  private val container = AppContainer.of(app)
  private val repo = container.repository

  private val _state = MutableStateFlow<ConnState>(ConnState.Loading)
  val state: StateFlow<ConnState> = _state.asStateFlow()

  private val _baseUrl = MutableStateFlow("")
  val baseUrl: StateFlow<String> = _baseUrl.asStateFlow()

  private val _busy = MutableStateFlow(false)
  val busy: StateFlow<Boolean> = _busy.asStateFlow()

  /** 登录页要能退回改地址，所以用一个开关而不是两个动作。 */
  private val _showServerForm = MutableStateFlow(false)
  val showServerForm: StateFlow<Boolean> = _showServerForm.asStateFlow()

  init {
    viewModelScope.launch {
      _baseUrl.value = repo.savedBaseUrl()
      _state.value = repo.probe()
    }
    // 用着用着会话过期（cron 跑着、服务端重启换了 INKCAL_SECRET）→ 弹回登录页
    viewModelScope.launch {
      repo.unauthorized.collect { expired ->
        if (expired) {
          _state.value = ConnState.NeedLogin
          repo.acknowledgeUnauthorized()
        }
      }
    }
  }

  fun saveServer(input: String) {
    viewModelScope.launch {
      _busy.value = true
      val normalized = repo.saveBaseUrl(input)
      if (normalized == null) {
        _state.value = ConnState.Failed("请填写服务器地址")
      } else {
        _baseUrl.value = normalized
        _showServerForm.value = false
        _state.value = repo.probe()
      }
      _busy.value = false
    }
  }

  fun login(user: String, password: String) {
    viewModelScope.launch {
      _busy.value = true
      _state.value = repo.login(user, password)
      _busy.value = false
    }
  }

  fun logout() {
    viewModelScope.launch {
      _busy.value = true
      _state.value = repo.logout()
      _busy.value = false
    }
  }

  fun toggleServerForm() {
    _showServerForm.value = !_showServerForm.value
  }

  fun retry() {
    viewModelScope.launch {
      _busy.value = true
      _state.value = repo.probe()
      _busy.value = false
    }
  }

  /**
   * §8.6：取一次数据版本，变了就广播全局刷新。
   *
   * 基线存在 ViewModel 里（不是轮询协程里）：协程在进后台时会被取消，
   * 基线跟着丢的话，回前台第一次轮询只会把「后台期间 cron 写的新版本」记成新基线，
   * 那些记录就再也触发不了刷新了。
   */
  suspend fun checkDataVersion() {
    val version = runCatching { repo.dataVersion() }.getOrNull() ?: return
    val previous = lastDataVersion
    lastDataVersion = version
    if (previous != null && previous != version) container.dataSignal.bump()
  }

  /** 上次见到的数据版本；null 表示还没取到过（首次只记基线，不刷）。 */
  private var lastDataVersion: String? = null
}
