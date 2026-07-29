<template>
  <div class="page">
    <div class="app-container">
      <header>
        <div class="brand">
          <span class="brand-mark">◎</span>
          <h1>Video Search</h1>
        </div>
        <nav>
          <button @click="currentPage = 'search'" :class="{ active: currentPage === 'search' }">Search</button>
          <button @click="currentPage = 'about'" :class="{ active: currentPage === 'about' }">About</button>
        </nav>
      </header>

      <main>
        <div v-if="currentPage === 'search'" class="main-content">
          <!-- Form Section -->
          <section class="panel form-panel">
            <h2 class="panel-title">New Search</h2>

            <div class="input-group">
              <label class="field-label">Video URL</label>
              <input v-model="videoUrl" placeholder="https://…" class="input-field" />

              <label class="field-label">New record label</label>
              <input v-model="record" placeholder="Name this recording" class="input-field" />

              <label class="field-label">Or choose a previous record</label>
              <select v-model="selectedRecord" class="record-select">
                <option disabled value="">Select a previous record</option>
                <option v-for="(rec, index) in records" :key="index" :value="rec">{{ rec }}</option>
              </select>

              <label class="field-label">Keyword</label>
              <input v-model="keyword" placeholder="Word or phrase to find" class="input-field" />
            </div>

            <button
              @click="keywordSearch"
              :disabled="isLoading || (!videoUrl && !record && !selectedRecord)"
              class="search-button"
            >
              <span v-if="!isLoading">Search</span>
              <span v-else>Searching…</span>
            </button>

            <transition name="fade">
              <div v-if="isLoading" class="status-card status-info">
                <template v-if="jobProgress">
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

          <!-- Results Section -->
          <section class="panel results-panel">
            <div class="results-header">
              <h2 class="panel-title">Results</h2>
              <span v-if="searchPerformed && results.length" class="result-count-badge">
                {{ results.length }} {{ results.length === 1 ? 'match' : 'matches' }}
              </span>
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
            Simply provide a URL to the video, enter a record label, or select a previous entry, and enter a keyword.
            All relevant results will be displayed with their corresponding start and end times.
          </p>
        </section>
      </main>
    </div>
  </div>
</template>

<script>
import axios from 'axios';
import { ref, onMounted } from 'vue';

export default {
  setup() {
    const videoUrl = ref('');
    const record = ref('');
    const selectedRecord = ref('');
    const keyword = ref('');
    const results = ref([]);
    const records = ref([]);
    const isLoading = ref(false);
    const searchPerformed = ref(false);
    const errorMessage = ref('');
    const jobProgress = ref(null);

    onMounted(async () => {
      try {
        const response = await axios.get('/api/records');
        records.value = response.data.records || [];
      } catch (error) {
        console.error('Error fetching records:', error);
        errorMessage.value = 'Could not load previous records.';
      }
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
      try {
        const recordToUse = selectedRecord.value || record.value;

        let response = await axios.post('/api/search', {
          url: videoUrl.value,
          record: recordToUse,
          keyword: keyword.value,
        });

        if (response.status === 202) {
          await waitForJob(response.data.job_id);
          if (!records.value.includes(recordToUse)) {
            records.value.push(recordToUse);
          }
          response = await axios.post('/api/search', {
            record: recordToUse,
            keyword: keyword.value,
          });
        }

        results.value = response.data.results || [];
        searchPerformed.value = true;
      } catch (error) {
        console.error('Error fetching search results:', error);
        errorMessage.value =
          error.response?.data?.error || error.message || 'Something went wrong.';
      } finally {
        isLoading.value = false;
        jobProgress.value = null;
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

    return {
      videoUrl,
      record,
      selectedRecord,
      keyword,
      results,
      records,
      isLoading,
      keywordSearch,
      currentPage,
      searchPerformed,
      errorMessage,
      jobProgress,
      speakerColor,
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

  .form-panel,
  .results-panel {
    width: 100%;
  }
}
</style>
