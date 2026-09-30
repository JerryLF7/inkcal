package com.jerrylf.inkcal.ui.app

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.jerrylf.inkcal.data.AppRepository
import com.jerrylf.inkcal.data.ConnState
import com.jerrylf.inkcal.data.CookieStore
import com.jerrylf.inkcal.data.SettingsStore
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

/**
 * App 级状态：服务器地址与登录状态。会话内只有一个实例（挂在 Activity 上）。
 *
 * 地址与 cookie 由 SettingsStore/CookieStore 持久化，这里只做编排。
 */
class AppViewModel(app: Application) : AndroidViewModel(app) {

  private val store = SettingsStore(app)
  private val cookieStore = CookieStore(store)
  private val repo = AppRepository(store, cookieStore)

  private val _state = MutableStateFlow<ConnState>(ConnState.Loading)
  val state: StateFlow<ConnState> = _state.asStateFlow()

  private val _baseUrl = MutableStateFlow("")
  val baseUrl: StateFlow<String> = _baseUrl.asStateFlow()

  private val _busy = MutableStateFlow(false)
  val busy: StateFlow<Boolean> = _busy.asStateFlow()

  /** 登录页要能退回改地址，所以状态本身就够用。 */
  private val _showServerForm = MutableStateFlow(false)
  val showServerForm: StateFlow<Boolean> = _showServerForm.asStateFlow()

  init {
    viewModelScope.launch {
      _baseUrl.value = repo.savedBaseUrl()
      _state.value = repo.probeSaved()
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
        _state.value = repo.probeSaved()
      }
      _busy.value = false
    }
  }

  fun login(user: String, password: String) {
    viewModelScope.launch {
      _busy.value = true
      _state.value = repo.login(_baseUrl.value, user, password)
      _busy.value = false
    }
  }

  fun logout() {
    viewModelScope.launch {
      _busy.value = true
      _state.value = repo.logout(_baseUrl.value)
      _busy.value = false
    }
  }

  /** 登录页要能退回改地址，所以用一个开关而不是两个动作。 */
  fun toggleServerForm() {
    _showServerForm.value = !_showServerForm.value
  }

  fun retry() {
    viewModelScope.launch {
      _busy.value = true
      _state.value = repo.probeSaved()
      _busy.value = false
    }
  }
}
