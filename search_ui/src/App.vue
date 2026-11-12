<template>
  <div class="page">
    <div class="app-container">
      <header>
        <div class="brand">
          <span class="brand-mark">◎</span>
          <h1>Video Search</h1>
        </div>
        <div v-if="user" class="account-chip">
          <span class="account-email">{{ user.email }}</span>
          <button type="button" class="account-logout" @click="logout">Log out</button>
        </div>
        <nav>
          <button @click="currentPage = 'search'" :class="{ active: currentPage === 'search' }">Search</button>
          <button @click="currentPage = 'about'" :class="{ active: currentPage === 'about' }">About</button>
        </nav>
      </header>

      <main>
        <div v-if="currentPage === 'search'" class="main-content">
          <div class="left-column">
          <!-- Account Section -->
          <section v-if="!user" class="panel account-panel">
            <h2 class="panel-title">{{ authMode === 'login' ? 'Log in' : 'Create account' }}</h2>
            <form class="input-group" @submit.prevent="submitAuth">
              <label class="field-label" for="auth-email">Email</label>
              <input id="auth-email" v-model="authEmail" type="email" autocomplete="email" class="input-field" />
              <label class="field-label" for="auth-password">Password</label>
              <input
                id="auth-password"
                v-model="authPassword"
                type="password"
                :autocomplete="authMode === 'login' ? 'current-password' : 'new-password'"
                class="input-field"
              />
              <p v-if="authMode === 'signup'" class="field-hint">8 to 128 characters.</p>
              <button
                type="submit"
                class="search-button"
                :disabled="authBusy || !authEmail || !authPassword"
              >{{ authBusy ? 'Please wait…' : authMode === 'login' ? 'Log in' : 'Sign up' }}</button>
            </form>
            <p v-if="authError" class="auth-error">{{ authError }}</p>
            <button type="button" class="auth-switch" @click="toggleAuthMode">
              {{ authMode === 'login' ? 'No account? Create one' : 'Have an account? Log in' }}
            </button>
            <p class="field-hint">Searching without an account only shows recordings that existed before accounts.</p>
          </section>

          <section v-else class="panel usage-panel">
            <h2 class="panel-title">Usage this month</h2>
            <template v-if="usage">
              <div
                class="progress-track usage-track"
                role="progressbar"
                aria-valuemin="0"
                aria-valuemax="100"
                :aria-valuenow="usagePct"
              >
                <div
                  class="progress-fill"
                  :class="{ 'usage-over': overQuota }"
                  :style="{ width: usagePct + '%' }"
                ></div>
              </div>
              <p class="status-sub">{{ usageText }}</p>
              <p v-if="overQuota" class="auth-error">
                Free tier used up. Existing recordings stay searchable; new ones resume next month.
              </p>
            </template>
            <p v-else class="field-hint">Usage unavailable right now.</p>
          </section>

          <!-- Form Section -->
          <section class="panel form-panel">
            <h2 class="panel-title">New Search</h2>

            <div class="input-group">
              <label class="field-label">Video URL</label>
              <input v-model="videoUrl" placeholder="https://…" class="input-field" />

              <label class="field-label">New record label</label>
              <input v-model="record" placeholder="Name this recording" class="input-field" />

              <label class="field-label">Or upload a file</label>
              <div
                class="dropzone"
                :class="{ dragging: isDragging, disabled: !!selectedRecord || isLoading }"
                @dragover.prevent="onDragOver"
                @dragleave.prevent="isDragging = false"
                @drop.prevent="onDrop"
                @click="openPicker"
                @keydown.enter.prevent="openPicker"
                @keydown.space.prevent="openPicker"
                role="button"
                tabindex="0"
                :aria-disabled="!!selectedRecord || isLoading"
              >
                <input
                  ref="fileInput"
                  type="file"
                  class="file-input"
                  :accept="uploadAccept"
                  @change="onFilePicked"
                />
                <template v-if="file">
                  <span class="dropzone-name">{{ file.name }}</span>
                  <span class="dropzone-meta">{{ formatBytes(file.size) }}</span>
                  <button
                    type="button"
                    class="dropzone-clear"
                    :disabled="isLoading"
                    @click.stop="clearFile"
                  >Remove</button>
                </template>
                <span v-else class="dropzone-meta">Drop an audio or video file here, or click to browse</span>
              </div>
              <p class="field-hint">Used instead of the URL when a file is chosen.</p>

              <label class="field-label">Or choose a previous record</label>
              <select v-model="selectedRecord" class="record-select">
                <option disabled value="">Select a previous record</option>
                <option v-for="(rec, index) in records" :key="index" :value="rec">{{ rec }}</option>
              </select>

              <label class="field-label" for="language">Spoken language</label>
              <select
                id="language"
                v-model="language"
                class="record-select"
                :disabled="!!selectedRecord"
              >
                <option value="auto">Auto-detect</option>
                <option v-for="[code, label] in languages" :key="code" :value="code">{{ label }}</option>
              </select>
              <p class="field-hint">Applies to new records only.</p>

              <label class="field-label">Keyword</label>
              <input v-model="keyword" placeholder="Word or phrase to find" class="input-field" />
            </div>

            <button
              @click="keywordSearch"
              :disabled="isLoading || (!videoUrl && !record && !selectedRecord && !file)"
              class="search-button"
            >
              <span v-if="!isLoading">Search</span>
              <span v-else>Searching…</span>
            </button>

            <transition name="fade">
              <div v-if="isLoading" class="status-card status-info">
                <template v-if="uploadProgress !== null">
                  <p class="status-title">Uploading {{ file?.name }}</p>
                  <div class="progress-track">
                    <div class="progress-fill" :style="{ width: uploadProgress + '%' }"></div>
                  </div>
                  <p class="status-sub">{{ uploadProgress }}% uploaded</p>
                </template>
                <template v-else-if="jobProgress">
                  <p class="status-title">Transcribing {{ jobProgress.status }}</p>
                  <div class="progress-track">
                    <div class="progress-fill" :style="{ width: jobProgress.progress + '%' }"></div>
                  </div>
                  <p class="status-sub">{{ jobProgress.progress }}% complete</p>
                </template>
                <p v-else class="status-title">Processing your search…</p>
              </div>
            </transition>

            <transition name="fade">
              <div v-if="errorMessage" class="status-card status-error">
                <p class="status-title">{{ errorMessage }}</p>
              </div>
            </transition>
          </section>
          </div>

          <!-- Results Section -->
          <section class="panel results-panel">
            <div class="results-header">
              <h2 class="panel-title">Results</h2>
              <span v-if="searchPerformed && results.length" class="result-count-badge">
                {{ results.length }} {{ results.length === 1 ? 'match' : 'matches' }}
              </span>
            </div>

            <div v-if="searchPerformed && videoId" class="export-actions">
              <span class="export-label">Export transcript</span>
              <div class="export-links">
                <button
                  v-for="fmt in exportFormats"
                  :key="fmt"
                  type="button"
                  class="export-link"
                  @click="downloadExport(fmt)"
                >{{ fmt.toUpperCase() }}</button>
              </div>
            </div>

            <div v-if="!searchPerformed" class="placeholder-state">
              <p>Enter a video URL and record label — or pick a previous entry — then search for a keyword to jump straight to the moment it's spoken.</p>
            </div>
            <div v-else>
              <ul v-if="results.length > 0" class="results-list">
                <li v-for="(result, index) in results" :key="index" class="result-item">
                  <span
                    class="speaker-badge"
                    :style="{ backgroundColor: speakerColor(result.speaker) }"
                  >{{ result.speaker || 'UNKNOWN' }}</span>
                  <span class="result-word">{{ result.word }}</span>
                  <span class="result-time">{{ result.start }}s – {{ result.end }}s</span>
                </li>
              </ul>
              <div v-else class="empty-state">
                <p>No results found for that keyword.</p>
              </div>
            </div>
          </section>
        </div>

        <!-- About -->
        <section v-else class="panel about-panel">
          <h2 class="panel-title">About</h2>
          <p>
            This application allows users to search within videos by keyword and navigate to specific timestamps where a keyword is mentioned.
            Provide a URL to the video, or drag and drop an audio or video file, enter a record label (optional for uploads), or select a previous entry, and enter a keyword.
            All relevant results will be displayed with their corresponding start and end times.
          </p>
        </section>
      </main>
    </div>
  </div>
</template>

<script>
import axios from 'axios';
import { ref, computed, onMounted } from 'vue';
import { LANGUAGES } from './languages';
import {
  UPLOAD_ACCEPT,
  isAllowedUpload,
  labelFromFilename,
  formatBytes,
} from './uploadTypes';
import {
  loadToken,
  saveToken,
  clearToken,
  authHeader,
  usagePercent,
  usageLabel,
  isOverQuota,
} from './auth';

export default {
  setup() {
    const videoUrl = ref('');
    const record = ref('');
    const selectedRecord = ref('');
    const keyword = ref('');
    const language = ref('auto');
    const languages = LANGUAGES;
    const results = ref([]);
    const records = ref([]);
    const isLoading = ref(false);
    const searchPerformed = ref(false);
    const errorMessage = ref('');
    const jobProgress = ref(null);
    const videoId = ref(null);
    const exportFormats = ['srt', 'vtt', 'txt', 'json'];
    const uploadAccept = UPLOAD_ACCEPT;
    const file = ref(null);
    const fileInput = ref(null);
    const isDragging = ref(false);
    const uploadProgress = ref(null);

    const setFile = (picked) => {
      if (!picked) return;
      if (!isAllowedUpload(picked.name)) {
        errorMessage.value = 'Unsupported file type. Choose an audio or video file.';
        return;
      }
      errorMessage.value = '';
      file.value = picked;
    };
    const clearFile = () => {
      file.value = null;
      if (fileInput.value) fileInput.value.value = '';
    };
    const uploadBlocked = () => isLoading.value || !!selectedRecord.value;
    const openPicker = () => {
      if (!uploadBlocked()) fileInput.value?.click();
    };
    const onFilePicked = (event) => setFile(event.target.files?.[0]);
    const onDragOver = () => {
      if (!uploadBlocked()) isDragging.value = true;
    };
    const onDrop = (event) => {
      isDragging.value = false;
      if (!uploadBlocked()) setFile(event.dataTransfer?.files?.[0]);
    };

    const user = ref(null);
    const usage = ref(null);
    const authMode = ref('login');
    const authEmail = ref('');
    const authPassword = ref('');
    const authError = ref('');
    const authBusy = ref(false);

    const usagePct = computed(() => usagePercent(usage.value));
    const usageText = computed(() => usageLabel(usage.value));
    const overQuota = computed(() => isOverQuota(usage.value));

    const applyToken = (token) => {
      const header = authHeader(token);
      if (header) axios.defaults.headers.common.Authorization = header;
      else delete axios.defaults.headers.common.Authorization;
    };

    const loadRecords = async () => {
      try {
        const response = await axios.get('/api/records');
        records.value = response.data.records || [];
      } catch (error) {
        console.error('Error fetching records:', error);
        errorMessage.value = 'Could not load previous records.';
      }
    };

    const refreshUsage = async () => {
      if (!user.value) {
        usage.value = null;
        return;
      }
      try {
        usage.value = (await axios.get('/api/usage')).data;
      } catch (error) {
        console.error('Error fetching usage:', error);
        usage.value = null;
      }
    };

    // Clears everything tied to the previous viewer, then reloads for the new one.
    const resetViewer = async () => {
      selectedRecord.value = '';
      results.value = [];
      searchPerformed.value = false;
      videoId.value = null;
      errorMessage.value = '';
      records.value = [];
      await Promise.all([loadRecords(), refreshUsage()]);
    };

    const startSession = async (token, sessionUser) => {
      saveToken(window.localStorage, token);
      applyToken(token);
      user.value = sessionUser;
      authPassword.value = '';
      await resetViewer();
    };

    const submitAuth = async () => {
      authBusy.value = true;
      authError.value = '';
      try {
        const path = authMode.value === 'login' ? '/api/login' : '/api/signup';
        const { data } = await axios.post(path, {
          email: authEmail.value,
          password: authPassword.value,
        });
        await startSession(data.token, data.user);
      } catch (error) {
        authError.value = error.response?.data?.error || error.message || 'Something went wrong.';
      } finally {
        authBusy.value = false;
      }
    };

    const toggleAuthMode = () => {
      authMode.value = authMode.value === 'login' ? 'signup' : 'login';
      authError.value = '';
    };

    const logout = async () => {
      try {
        await axios.post('/api/logout');
      } catch (error) {
        // an already-expired session is still logged out locally
        console.error('Error logging out:', error);
      }
      clearToken(window.localStorage);
      applyToken('');
      user.value = null;
      usage.value = null;
      await resetViewer();
    };

    onMounted(async () => {
      const token = loadToken(window.localStorage);
      if (token) {
        applyToken(token);
        try {
          user.value = (await axios.get('/api/me')).data.user;
        } catch (error) {
          // expired or revoked: continue anonymously
          if (error.response?.status === 401) {
            clearToken(window.localStorage);
            applyToken('');
          }
        }
      }
      await Promise.all([loadRecords(), refreshUsage()]);
    });

    const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

    // Poll the job until it finishes; throws on job failure.
    const waitForJob = async (jobId) => {
      for (;;) {
        const { data: job } = await axios.get(`/api/jobs/${jobId}`);
        jobProgress.value = { status: job.status, progress: job.progress };
        if (job.status === 'done') return;
        if (job.status === 'error') {
          throw new Error(job.error || 'Transcription failed.');
        }
        await sleep(2000);
      }
    };

    const keywordSearch = async () => {
      isLoading.value = true;
      searchPerformed.value = false;
      errorMessage.value = '';
      jobProgress.value = null;
      uploadProgress.value = null;
      videoId.value = null;
      try {
        const uploading = !!file.value && !selectedRecord.value;
        const recordToUse =
          selectedRecord.value ||
          record.value ||
          (uploading ? labelFromFilename(file.value.name) : '');

        let response;
        if (uploading) {
          const form = new FormData();
          form.append('file', file.value);
          form.append('record', recordToUse);
          form.append('language', language.value);
          uploadProgress.value = 0;
          response = await axios.post('/api/upload', form, {
            onUploadProgress: (e) => {
              if (e.total) uploadProgress.value = Math.round((e.loaded / e.total) * 100);
            },
          });
          uploadProgress.value = null;
        } else {
          response = await axios.post('/api/search', {
            url: videoUrl.value,
            record: recordToUse,
            keyword: keyword.value,
            language: language.value,
          });
        }

        if (response.status === 202) {
          await waitForJob(response.data.job_id);
          refreshUsage();
          if (!records.value.includes(recordToUse)) {
            records.value.push(recordToUse);
          }
          if (uploading) clearFile();
          response = await axios.post('/api/search', {
            record: recordToUse,
            keyword: keyword.value,
          });
        }

        results.value = response.data.results || [];
        videoId.value = response.data.video_id || null;
        searchPerformed.value = true;
      } catch (error) {
        console.error('Error fetching search results:', error);
        errorMessage.value =
          error.response?.data?.error || error.message || 'Something went wrong.';
      } finally {
        isLoading.value = false;
        jobProgress.value = null;
        uploadProgress.value = null;
        refreshUsage();
      }
    };

    const currentPage = ref('search');

    // Stable color per speaker label so the same speaker always reads the same hue.
    const speakerPalette = [
      'var(--speaker-hue-1)',
      'var(--speaker-hue-2)',
      'var(--speaker-hue-3)',
      'var(--speaker-hue-4)',
      'var(--speaker-hue-5)',
      'var(--speaker-hue-6)',
    ];
    const speakerColor = (label) => {
      const key = label || 'UNKNOWN';
      let hash = 0;
      for (let i = 0; i < key.length; i++) {
        hash = (hash * 31 + key.charCodeAt(i)) >>> 0;
      }
      return speakerPalette[hash % speakerPalette.length];
    };

    // The bearer token can't ride on a plain link, so fetch the file and save the blob.
    const downloadExport = async (fmt) => {
      try {
        const { data } = await axios.get(`/api/export/${videoId.value}`, {
          params: { format: fmt },
          responseType: 'blob',
        });
        const href = URL.createObjectURL(data);
        const link = document.createElement('a');
        link.href = href;
        link.download = `${videoId.value}.${fmt}`;
        document.body.appendChild(link);
        link.click();
        link.remove();
        URL.revokeObjectURL(href);
      } catch (error) {
        console.error('Error exporting transcript:', error);
        errorMessage.value = 'Could not export the transcript.';
      }
    };

    return {
      videoUrl,
      record,
      selectedRecord,
      keyword,
      language,
      languages,
      file,
      fileInput,
      isDragging,
      uploadProgress,
      uploadAccept,
      formatBytes,
      openPicker,
      onFilePicked,
      onDragOver,
      onDrop,
      clearFile,
      results,
      records,
      isLoading,
      keywordSearch,
      currentPage,
      searchPerformed,
      errorMessage,
      jobProgress,
      speakerColor,
      videoId,
      exportFormats,
      downloadExport,
      user,
      usage,
      usagePct,
      usageText,
      overQuota,
      authMode,
      authEmail,
      authPassword,
      authError,
      authBusy,
      submitAuth,
      toggleAuthMode,
      logout,
    };
  }
};
</script>

<style scoped>
.page {
  min-height: 100vh;
  display: flex;
  justify-content: center;
  padding: 3rem 1.5rem;
}

.app-container {
  max-width: 1080px;
  width: 100%;
}

header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 2.25rem;
}

.brand {
  display: flex;
  align-items: center;
  gap: 0.6rem;
}

.brand-mark {
  font-size: 1.4rem;
  color: var(--color-accent);
}

header h1 {
  font-size: 1.5rem;
  font-weight: 600;
  letter-spacing: -0.01em;
  color: var(--color-text);
}

nav {
  display: flex;
  gap: 0.25rem;
  background: var(--color-surface);
  border: 1px solid var(--color-border-soft);
  border-radius: 999px;
  padding: 0.25rem;
  box-shadow: var(--shadow-sm);
}

nav button {
  background: none;
  border: none;
  cursor: pointer;
  padding: 0.5rem 1.1rem;
  font-size: 0.9rem;
  font-weight: 500;
  color: var(--color-text-secondary);
  border-radius: 999px;
  transition: background-color 0.2s ease, color 0.2s ease;
}

nav button:hover {
  color: var(--color-text);
}

nav button.active {
  color: #fff;
  background: var(--color-accent);
}

.main-content {
  display: flex;
  gap: 1.5rem;
  align-items: flex-start;
}

.panel {
  background: var(--color-surface);
  border: 1px solid var(--color-border-soft);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-md);
  padding: 1.75rem;
}

.panel-title {
  font-size: 1.05rem;
  font-weight: 600;
  letter-spacing: -0.01em;
  margin-bottom: 1.25rem;
  color: var(--color-text);
}

.form-panel {
  flex: 1;
  min-width: 320px;
}

.input-group {
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
  margin-bottom: 1.5rem;
}

.field-label {
  font-size: 0.78rem;
  font-weight: 500;
  color: var(--color-text-tertiary);
  margin-top: 0.75rem;
}

.field-label:first-child {
  margin-top: 0;
}

.input-field,
.record-select {
  padding: 0.65rem 0.85rem;
  font-size: 0.95rem;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: var(--color-surface-soft);
  color: var(--color-text);
  transition: border-color 0.2s ease, box-shadow 0.2s ease;
}

.input-field:focus,
.record-select:focus {
  outline: none;
  border-color: var(--color-accent);
  box-shadow: 0 0 0 4px var(--color-accent-soft);
}

.file-input {
  display: none;
}

.dropzone {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.6rem;
  flex-wrap: wrap;
  padding: 1rem;
  text-align: center;
  border: 1.5px dashed var(--color-border);
  border-radius: var(--radius-sm);
  background: var(--color-surface-soft);
  cursor: pointer;
  transition: border-color 0.2s ease, background-color 0.2s ease;
}

.dropzone:hover:not(.disabled),
.dropzone:focus-visible,
.dropzone.dragging {
  outline: none;
  border-color: var(--color-accent);
  background: var(--color-accent-soft);
}

.dropzone.disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.dropzone-name {
  font-size: 0.9rem;
  font-weight: 600;
  color: var(--color-text);
  word-break: break-all;
}

.dropzone-meta {
  font-size: 0.8rem;
  color: var(--color-text-tertiary);
}

.dropzone-clear {
  background: none;
  border: none;
  cursor: pointer;
  font-size: 0.78rem;
  font-weight: 600;
  color: var(--color-error);
}

.search-button {
  width: 100%;
  background-color: var(--color-accent);
  color: white;
  border: none;
  padding: 0.75rem 1.5rem;
  font-size: 0.95rem;
  font-weight: 600;
  cursor: pointer;
  border-radius: var(--radius-sm);
  transition: background-color 0.2s ease, transform 0.1s ease;
}

.search-button:hover:not(:disabled) {
  background-color: var(--color-accent-hover);
}

.search-button:active:not(:disabled) {
  transform: scale(0.98);
}

.search-button:disabled {
  background-color: var(--color-border);
  color: var(--color-text-tertiary);
  cursor: not-allowed;
}

.status-card {
  margin-top: 1rem;
  padding: 0.85rem 1rem;
  border-radius: var(--radius-sm);
  font-size: 0.9rem;
}

.status-info {
  background: var(--color-accent-soft);
  color: var(--color-accent);
}

.status-error {
  background: var(--color-error-soft);
  color: var(--color-error);
}

.status-title {
  font-weight: 600;
  margin-bottom: 0.1rem;
}

.field-hint {
  font-size: 0.75rem;
  color: var(--color-text-tertiary);
  margin-top: 0.25rem;
}

.status-sub {
  font-size: 0.8rem;
  opacity: 0.85;
  margin-top: 0.35rem;
}

.progress-track {
  width: 100%;
  height: 6px;
  background-color: rgba(0, 0, 0, 0.08);
  border-radius: 999px;
  overflow: hidden;
  margin-top: 0.5rem;
}

.progress-fill {
  height: 100%;
  background-color: var(--color-accent);
  border-radius: 999px;
  transition: width 0.5s ease;
}

.results-panel {
  flex: 2;
}

.results-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 1.25rem;
}

.results-header .panel-title {
  margin-bottom: 0;
}

.result-count-badge {
  font-size: 0.78rem;
  font-weight: 600;
  color: var(--color-success);
  background: var(--color-success-soft);
  padding: 0.3rem 0.65rem;
  border-radius: 999px;
}

.export-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  padding: 0.6rem 0.85rem;
  margin-bottom: 1.25rem;
  background: var(--color-surface-soft);
  border: 1px solid var(--color-border-soft);
  border-radius: var(--radius-sm);
}

.export-label {
  font-size: 0.78rem;
  font-weight: 500;
  color: var(--color-text-tertiary);
}

.export-links {
  display: flex;
  gap: 0.4rem;
}

.export-link {
  font-size: 0.75rem;
  font-weight: 600;
  color: var(--color-accent);
  background: var(--color-accent-soft);
  padding: 0.3rem 0.6rem;
  border-radius: 999px;
  transition: background-color 0.2s ease, color 0.2s ease;
}

.export-link:hover {
  background: var(--color-accent);
  color: #fff;
  opacity: 1;
}

.placeholder-state {
  color: var(--color-text-tertiary);
  font-size: 0.92rem;
  line-height: 1.6;
}

.results-list {
  list-style: none;
  padding: 0;
}

.result-item {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.75rem 0;
  border-bottom: 1px solid var(--color-border-soft);
  font-size: 0.92rem;
}

.result-item:last-child {
  border-bottom: none;
}

.speaker-badge {
  display: inline-flex;
  align-items: center;
  flex-shrink: 0;
  color: #fff;
  font-size: 0.72rem;
  font-weight: 700;
  letter-spacing: 0.02em;
  padding: 0.25rem 0.55rem;
  border-radius: 999px;
}

.result-word {
  flex: 1;
  color: var(--color-text);
  font-weight: 500;
}

.result-time {
  color: var(--color-text-tertiary);
  font-variant-numeric: tabular-nums;
  font-size: 0.85rem;
}

.empty-state {
  color: var(--color-text-tertiary);
  font-size: 0.92rem;
  padding: 1rem 0;
}

.about-panel {
  color: var(--color-text-secondary);
  font-size: 1rem;
  line-height: 1.7;
  max-width: 640px;
  margin: 0 auto;
}

.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.2s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

@media (max-width: 720px) {
  .main-content {
    flex-direction: column;
  }

  .left-column,
  .form-panel,
  .results-panel {
    width: 100%;
  }
}

.left-column {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
  min-width: 320px;
}

.account-chip {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  font-size: 0.85rem;
  color: var(--color-text-secondary);
}

.account-logout,
.auth-switch {
  background: none;
  border: none;
  padding: 0;
  cursor: pointer;
  font-size: 0.8rem;
  font-weight: 600;
  color: var(--color-accent);
}

.auth-switch {
  margin-top: 0.75rem;
}

.auth-error {
  margin-top: 0.6rem;
  font-size: 0.82rem;
  color: var(--color-error);
}

.usage-track {
  margin-top: 0;
}

.usage-over {
  background-color: var(--color-error);
}

.export-link {
  border: none;
  cursor: pointer;
}
</style>
