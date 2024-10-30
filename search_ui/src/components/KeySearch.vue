<template>
  <div class="keysearch">
    <h1>Search within Video</h1>
    <input v-model="videoUrl" placeholder="Enter Video URL" />
    <input v-model="keyword" placeholder="Enter a keyword" />
    <button @click="keywordSearch">Search</button>

    <div v-if="results.length > 0">
      <h2>Results:</h2>
      <ul>
        <li v-for="(result, index) in results" :key="index">
          Word: {{ result[0] }}, Start: {{ result[1] }}s, End: {{ result[2] }}s
          <button @click="jumpToTime(result[1])">Jump to Time</button>
        </li>
      </ul>
    </div>
  </div>
</template>

<script>
export default {
  data() {
    return {
      videoUrl: '',
      keyword: '',
      results: []
    };
  },
  methods: {
    async keywordSearch() {
      try {
        const response = await this.$axios.post('/api/search', {
          url: this.videoUrl
        }, {
          params: {
            keyword: this.keyword
          }
        });
        
        this.results = response.data.results;
        const videoId = response.data.video_id;
        console.log('Generated video_id:', videoId);

      } catch (error) {
        console.error('Error fetching search results:', error);
      }
    },
    jumpToTime(time) {
      const video = document.getElementById('videoPlayer');
      video.currentTime = time;
      video.play();
    }
  }
};
</script>

<style scoped>
h1 {
  font-weight: 500;
  font-size: 2.6rem;
  position: relative;
  top: -10px;
}

h3 {
  font-size: 1.2rem;
}

.greetings h1,
.greetings h3 {
  text-align: center;
}

@media (min-width: 1024px) {
  .greetings h1,
  .greetings h3 {
    text-align: left;
  }
}
</style>
