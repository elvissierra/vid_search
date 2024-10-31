<script>
import axios from 'axios';
import { ref } from 'vue';

export default {
  setup() {
    const videoUrl = ref('');
    const keyword = ref('');
    const results = ref([]);

    const keywordSearch = async () => {
      try {
        const response = await axios.post('/api/search', {
          url: videoUrl.value
        }, {
          params: {
            keyword: keyword.value
          }
        });

        results.value = response.data.results || [];
        console.log('Search results:', results.value);
      } catch (error) {
        console.error('Error fetching search results:', error);
      }
    };

    const jumpToTime = (time) => {
      const video = document.getElementById('videoPlayer');
      video.currentTime = time;
      video.play();
    };

    const currentPage = ref('search');

    return { videoUrl, keyword, results, keywordSearch, jumpToTime, currentPage };
  }
};
</script>

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
        <input v-model="keyword" placeholder="Enter a keyword" />
        <button @click="keywordSearch">Search</button>

        <div v-if="results.length > 0" class="results-container">
          <h2>Results:</h2>
          <ul class="results-list">
            <li v-for="(result, index) in results" :key="index">
              <span>Word: {{ result[0] }}, Start: {{ result[1] }}s, End: {{ result[2] }}s</span>
              <button @click="jumpToTime(result[1])">Jump to Time</button>
            </li>
          </ul>
        </div>
        <div v-else>
          <p>No results found for the keyword "{{ keyword }}"</p>
        </div>
      </section>

      <section v-else class="about-section">
        <h2>About</h2>
        <p>This application allows users to search within videos by keyword and navigate to specific timestamps.</p>
      </section>
    </main>
  </div>
</template>

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
</style>
