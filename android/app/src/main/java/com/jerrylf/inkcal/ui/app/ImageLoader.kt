package com.jerrylf.inkcal.ui.app

import android.content.Context
import coil3.ImageLoader
import coil3.SingletonImageLoader
import coil3.network.okhttp.OkHttpNetworkFetcherFactory
import com.jerrylf.inkcal.data.AppContainer

/**
 * 图片一律走服务端代理，所以要复用 App 那个带会话 cookie 的 OkHttpClient，
 * 否则未登录的图片请求会被 Flask 401 掉。Coil 默认带磁盘缓存。
 *
 * 必须在第一次加载图片之前调用（MainActivity.onCreate）。
 */
fun installImageLoader(context: Context) {
  val client = AppContainer.of(context).repository.httpClient
  SingletonImageLoader.setSafe {
    ImageLoader.Builder(it)
      .components { add(OkHttpNetworkFetcherFactory(callFactory = { client })) }
      .build()
  }
}
