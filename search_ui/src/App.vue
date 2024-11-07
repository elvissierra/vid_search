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
      <div v-if="currentPage === 'search'" class="main-content">
        <!-- Form Section -->
        <div class="form-container">
          <div class="input-group">
            <input v-model="videoUrl" placeholder="Enter Video URL" class="input-field" />
            <input v-model="record" placeholder="Enter a new record label" class="input-field" />
            <select v-model="selectedRecord" class="record-select">
              <option disabled value="">Select a previous record</option>
              <option v-for="(rec, index) in records" :key="index" :value="rec">{{ rec }}</option>
            </select>
            <input v-model="keyword" placeholder="Enter a keyword" class="input-field" />
          </div>

          <button @click="keywordSearch" :disabled="isLoading || (!videoUrl && !record && !selectedRecord)" class="search-button">
            Search
          </button>

          <div v-if="isLoading" class="loading">
            <p>Processing your search...</p>
          </div>
        </div>

        <!-- Results Section -->
        <div class="results-container">
          <h2>Search Results</h2>
          <div v-if="!searchPerformed" class="placeholder-text">
            <p>Enter a video URL and record label or select a previous entry and keyword to search within the video.</p>
          </div>
          <div v-else>
            <ul v-if="results.length > 0" class="results-list">
              <li v-for="(result, index) in results" :key="index">
                <span>Word: {{ result[0] }} | Start: {{ result[1] }}s | End: {{ result[2] }}s</span>
              </li>
            </ul>
            <div v-else class="empty-state">
              <p>No results found for the given keyword.</p>
            </div>
          </div>
        </div>
      </div>
        <!-- About Vue -->
      <section v-else class="about-section">
        <p>
          This application allows users to search within videos by keyword and navigate to specific timestamps where a keyword is mentioned.
          Simply provide a URL to the video, enter a record label, or select a previous entry, and enter a keyword.
          All relevant results will be displayed with their corresponding start and end times.
        </p>
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
    const searchPerformed = ref(false);

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
      searchPerformed.value = false;
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
        searchPerformed.value = true;
      } catch (error) {
        console.error('Error fetching search results:', error);
      } finally {
        isLoading.value = false;
      }
    };

    const currentPage = ref('search');

    return { videoUrl, record, selectedRecord, keyword, results, records, isLoading, keywordSearch, currentPage, searchPerformed };
  }
};
</script>

<style scoped>
.app-container {
  max-width: 1100px;
  width: 100%;      
  margin: 0 auto;   
  padding: 20px;    
  font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
  background-color: #aca4a4;
  box-shadow: 0 0 15px rgba(0, 0, 0, 0.1);
  border-radius: 10px;
}

header {
  text-align: center;
  color: #fcfbfb;
  border-bottom: 2px solid #fcfbfb;
  padding-bottom: 1rem;
  margin-bottom: 2rem;
}

nav {
  margin-top: 1rem;
}

nav button {
  background: none;
  border: none;
  cursor: pointer;
  padding: 0.75rem 1.25rem;
  font-size: 1.1rem;
}

nav button.active {
  font-weight: bold;
  color: #0066cc;
  border-bottom: 2px solid #0066cc;
}

.main-content {
  display: flex;
  gap: 2rem;
  align-items: flex-start;
}

.form-container {
  flex: 1;
  text-align: center;
}

.input-group {
  display: flex;
  flex-direction: column;
  gap: 1rem;
  margin-bottom: 2rem;
}

.input-field {
  padding: 0.75rem;
  font-size: 1.1rem;
  border: 1px solid #8c9bee;
  border-radius: 8px;
}

.record-select {
  padding: 0.75rem;
  font-size: 1.1rem;
  border-radius: 8px;
  border: 1px solid #8c9bee;
}

.search-button {
  background-color: #28a745;
  color: white;
  border: none;
  padding: 0.75rem 1.5rem;
  font-size: 1.1rem;
  cursor: pointer;
  border-radius: 8px;
  transition: background-color 0.3s;
}

.search-button:hover {
  background-color: #218838;
}

.results-container .placeholder-text {
  color: #ddd;
  font-style: italic;
}

.results-container {
  flex: 2.5;
  background-color: rgb(118, 142, 203);
  padding: 20px;
  border-radius: 10px;
  box-shadow: 0 0 10px rgba(0, 0, 0, 0.1);
  max-width: 450px;
}

.results-container h2 {
  text-align: left;
  margin-bottom: 1rem;
  color: #ddd
}

.results-list {
  list-style: none;
  padding: 0;
  font-size: 1.1rem;
  color: #333;
}

.results-list li {
  margin-bottom: 0.75rem;
  border-bottom: 1px solid #ddd;
  padding-bottom: 0.5rem;
}

.loading {
  margin-top: 1rem;
  font-size: 1.1rem;
  color: #555;
}

.empty-state {
  margin-top: 1.5rem;
  font-size: 1.1rem;
  color: #999;
}

.about-section {
  text-align: center;
  color: #fcfbfb;
  font-size: 1.3rem;
}
</style>