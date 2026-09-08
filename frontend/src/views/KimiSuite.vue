<template>
  <div class="section">
    <div class="section-header"><div><h2 class="section-title">Kimi 能力测试集</h2><p class="subtitle">验证 kimi-k3 的参数兼容性、输出约束、工具调用与缓存 usage。</p></div><el-tag effect="plain">{{ selected.length }} / 9 Case</el-tag></div>
    <div class="section-body">
      <el-form :model="form" label-position="top">
        <div class="form-grid">
          <el-form-item label="测试名称"><el-input v-model="form.name" /></el-form-item>
          <el-form-item label="协议"><el-select v-model="form.api_protocol" disabled><el-option label="OpenAI-compatible" value="openai" /></el-select></el-form-item>
          <el-form-item label="接入域名"><el-input v-model="form.base_url" /></el-form-item>
          <el-form-item label="Endpoint"><el-input v-model="form.endpoint" /></el-form-item>
          <el-form-item label="模型"><el-input v-model="form.model" /></el-form-item>
          <el-form-item label="API Key"><el-input v-model="form.api_key" type="password" show-password /></el-form-item>
          <el-form-item label="最大输出 Token"><el-input-number v-model="form.max_output_tokens" :min="1" :max="65536" /></el-form-item>
          <el-form-item label="流式响应"><el-switch v-model="form.enable_stream" /></el-form-item>
        </div>
        <h3>测试 Case</h3>
        <div class="case-grid"><button v-for="item in cases" :key="item.id" type="button" class="case-card" :class="{ active: form.case_ids.includes(item.id) }" @click="toggle(item.id)"><strong>{{ item.name }}</strong><span>{{ item.description }}</span><em>{{ form.case_ids.includes(item.id) ? '已选择' : '点击选择' }}</em></button></div>
        <div class="submit-row"><el-button type="primary" :loading="loading" @click="submit">启动 Kimi 测试集（{{ selected.length }} 个 Case）</el-button></div>
      </el-form>
    </div>
  </div>
</template>
<script setup>
import { computed, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { createKimiSuite } from '../api/client'
const router = useRouter(); const loading = ref(false)
const cases = [
  ['cache_repeat','缓存命中-重复请求','相同消息重复请求'],['cache_multiturn','缓存命中-多轮对话','保留上下文新增一轮'],['cache_variable_suffix','缓存命中-尾部变化','只改变短尾部'],['thinking','思考控制-多场景','开启与关闭 thinking'],['json_output','JSON格式输出校验-多场景','验证 JSON 对象'],['stop','stop参数生效-多场景','数字与中文 stop'],['sampling','采样参数-多场景','temperature 与 top_p'],['tool_call','工具调用-多场景','函数名与参数'],['output_tokens','输出tokens校验-多场景','多个 max_tokens 上限']
].map(([id,name,description]) => ({ id, name, description }))
const form = reactive({ name:'Kimi 能力测试集', api_protocol:'openai', base_url:'https://api.wenwen-ai.com', endpoint:'/v1/chat/completions', model:'kimi-k3', api_key:'', max_output_tokens:128, enable_stream:true, case_ids:cases.map(item=>item.id) })
const selected = computed(() => form.case_ids)
function toggle(id) { form.case_ids = form.case_ids.includes(id) ? form.case_ids.filter(x=>x!==id) : [...form.case_ids,id] }
async function submit() { if (!form.api_key) return ElMessage.error('请输入 API Key'); if (!form.case_ids.length) return ElMessage.error('至少选择一个 Case'); loading.value=true; try { const result=await createKimiSuite(form); router.push(`/tests/kimi-suite/${result.test_id}`) } catch (e) { ElMessage.error(e.message) } finally { loading.value=false } }
</script>
<style scoped>.form-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px}.case-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px}.case-card{display:grid;gap:8px;min-height:130px;padding:16px;border:1px solid #d1d5db;border-radius:10px;background:#fff;text-align:left;cursor:pointer}.case-card.active{border-color:#2563eb;background:#eff6ff}.case-card span{color:#6b7280}.case-card em{color:#2563eb;font-style:normal;font-weight:700}.submit-row{margin-top:22px;text-align:right}@media(max-width:768px){.form-grid,.case-grid{grid-template-columns:1fr}}</style>
