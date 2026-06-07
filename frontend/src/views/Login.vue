<template>
  <div class="login-page">
    <div class="login-panel">
      <div class="login-brand">
        <img class="login-logo" src="https://wenwen-us.oss-us-west-1.aliyuncs.com/apipro_logo.png" alt="APIPro" />
        <div>
          <h1>APIPro LLM Benchmark Studio</h1>
          <p>请选择访问身份后继续</p>
        </div>
      </div>

      <el-form :model="form" label-position="top" @submit.prevent="submit">
        <el-form-item label="管理员账号">
          <el-input v-model="form.username" autocomplete="username" placeholder="root" />
        </el-form-item>
        <el-form-item label="管理员密码">
          <el-input
            v-model="form.password"
            type="password"
            show-password
            autocomplete="current-password"
            @keyup.enter="submit"
          />
        </el-form-item>
        <el-button type="primary" class="login-button" :loading="auth.loading" @click="submit">
          管理员登录
        </el-button>
        <el-button class="login-button guest-button" :loading="auth.loading" @click="loginAsGuest">
          游客进入
        </el-button>
      </el-form>
    </div>
  </div>
</template>

<script setup>
import { reactive } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '../stores/auth'

const router = useRouter()
const auth = useAuthStore()
const form = reactive({
  username: 'root',
  password: ''
})

async function submit() {
  if (!form.username.trim() || !form.password) {
    ElMessage.warning('请输入用户名和密码')
    return
  }
  try {
    await auth.login(form.username.trim(), form.password)
    router.replace('/')
  } catch (error) {
    ElMessage.error(error.message || '登录失败')
  }
}

async function loginAsGuest() {
  try {
    await auth.login('guest', '')
    router.replace('/')
  } catch (error) {
    ElMessage.error(error.message || '游客登录失败')
  }
}
</script>
