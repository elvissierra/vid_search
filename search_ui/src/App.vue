<template>
  <div class="app-container">
    <header>
      <h1>Video Search Application</h1>
      <nav>
        <button @click="currentPage = 'search'" :class="{ active: currentPage === 'search' }">Search</button>
        <button @click="currentPage = 'about'" :class="{ active: currentPage === 'about' }">About</button>
      </nav>
    </header>

    <main>
      <section v-if="currentPage === 'search'" class="search-section">
        <input v-model="videoUrl" placeholder="Enter Video URL" />

        <select v-model="selectedRecord" class="record-select">
          <option disabled value="">Select a previous record</option>
          <option v-for="(rec, index) in records" :key="index" :value="rec">{{ rec }}</option>
        </select>

        <input v-model="record" placeholder="Enter a new record label" />

        <input v-model="keyword" placeholder="Enter a keyword" />
        <button @click="keywordSearch" :disabled="isLoading || (!videoUrl && !record && !selectedRecord)">Search</button>

        <div v-if="isLoading" class="loading">
          <p>Processing your search...</p>
        </div>

        <div v-if="results.length > 0 && !isLoading" class="results-container">
          <h2>Results:</h2>
          <ul class="results-list">
            <li v-for="(result, index) in results" :key="index">
              <span>Word: {{ result[0] }} Start: {{ result[1] }}s, End: {{ result[2] }}s</span>
            </li>
          </ul>
        </div>

        <div v-else-if="!isLoading && results.length === 0" class="empty-state">
          <p>Enter a video URL, record label, and keyword to search within the video.</p>
        </div>
      </section>

      <section v-else class="about-section">
        <h2>About</h2>
        <p>This application allows users to search within videos by keyword and navigate to specific timestamps when a keyword is mentioned.</p>
      </section>
    </main>
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

    onMounted(async () => {
      try {
        const response = await axios.get('/api/records');
        records.value = response.data.records || [];
      } catch (error) {
        console.error('Error fetching records:', error);
      }
    });

    const keywordSearch = async () => {
      isLoading.value = true;
      try {
        const recordToUse = selectedRecord.value || record.value;

        const response = await axios.post('/api/search', {
          url: videoUrl.value,
          record: recordToUse,
        }, {
          params: {
            keyword: keyword.value
          }
        });

        results.value = response.data.results || [];
      } catch (error) {
        console.error('Error fetching search results:', error);
      } finally {
        isLoading.value = false;
      }
    };

    const currentPage = ref('search');

    return { videoUrl, record, selectedRecord, keyword, results, records, isLoading, keywordSearch, currentPage };
  }
};
</script>

<style scoped>
.app-container {
  max-width: 600px;
  margin: auto;
  padding: 20px;
  font-family: Arial, sans-serif;
}

header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-bottom: 2px solid #ddd;
  padding-bottom: 1rem;
  margin-bottom: 1rem;
}

nav {
  display: flex;
  gap: 1rem;
}

nav button {
  background: none;
  border: none;
  cursor: pointer;
  padding: 0.5rem 1rem;
  font-size: 1rem;
}

nav button.active {
  font-weight: bold;
  color: #007bff;
  border-bottom: 2px solid #007bff;
}

.search-section,
.about-section {
  text-align: center;
}

.results-container {
  margin-top: 1.5rem;
}

.results-list {
  list-style: none;
  padding: 0;
}

.results-list li {
  margin-bottom: 0.5rem;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

button {
  background-color: #007bff;
  color: white;
  border: none;
  padding: 0.5rem 1rem;
  cursor: pointer;
  border-radius: 5px;
  transition: background-color 0.3s;
}

button:hover {
  background-color: #0056b3;
}

.loading {
  margin-top: 1rem;
  font-size: 1rem;
  color: #555;
}

.empty-state {
  margin-top: 1.5rem;
  font-size: 1rem;
  color: #777;
}

.record-select {
  margin-top: 0.5rem;
  padding: 0.5rem;
  font-size: 1rem;
  width: 100%;
  border-radius: 4px;
  border: 1px solid #ddd;
}
</style>
