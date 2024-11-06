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

        <!-- Search Results Modal -->
        <div v-if="showModal && results.length > 0" class="modal-overlay" @click.self="closeModal">
          <div class="modal-content">
            <button class="close-modal" @click="closeModal">&times;</button>
            <h2>Search Results ({{ results.length }} found)</h2>
            <ul class="results-list">
              <li v-for="(result, index) in results" :key="index">
                <span>Word: {{ result[0] }} | Start: {{ result[1] }}s | End: {{ result[2] }}s</span>
              </li>
            </ul>
          </div>
        </div>

        <div v-else-if="!isLoading && results.length === 0" class="empty-state">
          <p>Enter a video URL and record label/ select a previous entry and keyword to search within the video.</p>
        </div>
      </section>

      <section v-else class="about-section">
        <p>
          This application allows users to search within videos by keyword and navigate to 
          specific timestamps where a keyword is mentioned. Simply provide a url to the video and
           enter a record label, or select a previous entry, and enter a keyword. All relavent 
           results will be display with their corresponding start and end times.
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
    const showModal = ref(false);

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
        if (results.value.length > 0) {
          showModal.value = true;
        }
      } catch (error) {
        console.error('Error fetching search results:', error);
      } finally {
        isLoading.value = false;
      }
    };

    const closeModal = () => {
      showModal.value = false;
    };

    const currentPage = ref('search');

    return { videoUrl, record, selectedRecord, keyword, results, records, isLoading, keywordSearch, currentPage, showModal, closeModal };
  }
};
</script>

<style scoped>
.app-container {
  max-width: 700px;
  margin: auto;
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

.search-section {
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

.loading {
  margin-top: 1rem;
  font-size: 1.1rem;
  color: #555;
}

.empty-state {
  margin-top: 1.5rem;
  font-size: 1.1rem;
  color: #dedbdb;
}

.modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background-color: rgba(0, 0, 0, 0.5);
  display: flex;
  justify-content: center;
  align-items: center;
}

.modal-content {
  background: white;
  padding: 2rem;
  border-radius: 10px;
  box-shadow: 0 0 15px rgba(0, 0, 0, 0.2);
  max-width: 90%;
  max-height: 80%;
  overflow-y: auto;
}

.close-modal {
  position: absolute;
  top: 10px;
  right: 10px;
  background: none;
  border: none;
  font-size: 2rem;
  cursor: pointer;
}

.results-list {
  list-style: none;
  padding: 0;
  margin-top: 1rem;
}

.results-list li {
  margin-bottom: 0.75rem;
  font-size: 1.1rem;
}

.about-section {
  text-align: center;
  color: #333;
}

.about-section p {
  color: #fcfbfb;
}
</style>