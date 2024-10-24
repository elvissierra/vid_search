import moviepy.editor as mp
import speech_recognition as sr
import whisper

"""video = mp.VideoFileClip("what.mp4")
audio_file = video.audio
audio_file.write_audiofile("what.wav")
r = sr.Recognizer()
chunk_duration = 2
with sr.AudioFile("what.wav") as source:
    total_duration = source.DURATION
    offset = 0
    while offset < total_duration:
        data = r.record(source, duration=total_duration, offset=offset)
        try:
            results = r.recognize_google(data, show_all=True)
            if isinstance(results, dict):
                for result in results["alternative"]:
                    if "confidence" in result:
                        print(f"Text: {result['transcript']} (Start: {offset} seconds, End: {offset + chunk_duration} seconds, Confidence: {result['confidence']})")
            else:
                print(f"Speech not recognized at: {offset} to {offset + chunk_duration}")

        except sr.UnknownValueError:
            print(f"Speech not recognized at: {offset} to {offset + chunk_duration}")
        offset += chunk_duration"""

model = whisper.load_model("tiny")
result = model.transcribe("what.mp4")
print(result["text"])