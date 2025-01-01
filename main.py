import os
import subprocess
import threading
import time
import tkinter as tk
from tkinter import filedialog, ttk
from pathlib import Path

import fitz  # PyMuPDF
import pyttsx3
from pydub import AudioSegment


def format_time(seconds):
    if seconds < 0:
        seconds = 0
    m, s = divmod(int(seconds), 60)
    return f"{m}dk {s}sn"


def extract_text_from_pdf(pdf_path):
    all_pages = []
    with fitz.open(pdf_path) as doc:
        for i in range(doc.page_count):
            page_text = doc.load_page(i).get_text("text")
            all_pages.append(page_text)
    return "\n".join(all_pages)


def split_text_into_chunks(text, chunk_size=300):
    words = text.split()
    total = len(words)
    chunks = []
    for i in range(0, total, chunk_size):
        chunk_words = words[i: i + chunk_size]
        chunks.append(" ".join(chunk_words))
    return chunks


def tts_chunk_to_wav_pyttsx3(chunk_text, wav_path, rate=150):
    engine = pyttsx3.init()
    engine.setProperty("rate", rate)
    engine.save_to_file(chunk_text, str(wav_path))
    engine.runAndWait()


def wav_to_mp3(wav_path, mp3_path, bitrate="128k"):
    audio = AudioSegment.from_wav(wav_path)
    audio.export(mp3_path, format="mp3", bitrate=bitrate)


def merge_mp3_ffmpeg(mp3_files, final_mp3, log_callback):
    list_file = "concat_list.txt"
    with open(list_file, "w", encoding="utf-8") as f:
        for mp3 in mp3_files:
            f.write(f"file '{mp3}'\n")

    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        list_file,
        "-c",
        "copy",
        str(final_mp3),
    ]

    log_callback("MP3 dosyaları ffmpeg ile birleştiriliyor...")
    subprocess.run(cmd, check=True)
    os.remove(list_file)


def pdf_to_mp3(pdf_path, chunk_size, rate, clean_parts, log_callback, time_callback):
    """
    1) PDF'den metin çıkar.
    2) Metni chunk_size kelimeye göre küçük parçalara ayır.
    3) Her bir parçayı (chunk) önce WAV, sonra MP3 olarak kaydet.
    4) Tüm küçük MP3 dosyalarını ffmpeg ile birleştir, final MP3 çıkar.
    5) clean_parts=True ise, parça MP3'ler silinir.
    6) time_callback ile her chunk sonunda kalan süre label'ını güncelle.
    """
    pdf_path = Path(pdf_path)
    pdf_stem = pdf_path.stem  # "document.pdf" -> "document"

    log_callback(f"PDF okunuyor: {pdf_path}")
    full_text = extract_text_from_pdf(pdf_path)
    if not full_text.strip():
        log_callback("PDF metni boş veya okunamadı. (Taranmış olabilir.)")
        return

    # outputs/DocumentName klasörü
    output_dir = Path("outputs") / pdf_stem
    output_dir.mkdir(parents=True, exist_ok=True)

    # Metni parçalara böl
    log_callback("Metin parçalara ayrılıyor...")
    chunks = split_text_into_chunks(full_text, chunk_size)
    total_chunks = len(chunks)
    log_callback(f"Toplam parça sayısı: {total_chunks}")

    mp3_files = []

    sum_of_chunk_times = 0.0  # Ortalama süre hesaplamak için
    for i, chunk_text in enumerate(chunks, start=1):
        start_t = time.time()

        # WAV oluştur
        wav_path = output_dir / f"part_{i}.wav"
        tts_chunk_to_wav_pyttsx3(chunk_text, wav_path, rate)

        # WAV -> MP3
        mp3_path = output_dir / f"part_{i}.mp3"
        wav_to_mp3(wav_path, mp3_path)
        mp3_files.append(mp3_path)

        # WAV'i silelim
        wav_path.unlink(missing_ok=True)

        end_t = time.time()
        chunk_duration = end_t - start_t
        sum_of_chunk_times += chunk_duration
        avg_chunk_time = sum_of_chunk_times / i

        chunks_left = total_chunks - i
        est_time_left = avg_chunk_time * chunks_left

        # Loga da yazıyoruz
        log_callback(
            f"Parça {i}/{total_chunks} tamamlandı. "
            f"Bu parça süresi: {format_time(chunk_duration)} | "
        )
        # UI'daki Label için time_callback
        time_callback(f"Kalan Süre: {format_time(est_time_left)}")

    # Son MP3
    final_mp3 = output_dir / f"{pdf_stem}_final.mp3"
    merge_mp3_ffmpeg(mp3_files, final_mp3, log_callback)
    log_callback(f"Final MP3 oluşturuldu: {final_mp3}")

    # Parçaları sil
    if clean_parts:
        log_callback("Küçük parça MP3 dosyaları siliniyor...")
        for f in mp3_files:
            f.unlink(missing_ok=True)
        log_callback("Tüm parça dosyaları silindi.")

    # Son olarak kalan süre label'ını sıfırla
    time_callback("Kalan Süre: 0dk 0sn")


class PDFtoMP3App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("PDF to MP3 Converter")
        self.geometry("700x450")

        # Seçilen PDF yolunu tutacağız
        self.pdf_path = ""

        # Ayarlar (chunk size, rate, vb.)
        self.chunk_size_var = tk.IntVar(value=300)
        self.rate_var = tk.IntVar(value=150)
        self.clean_parts_var = tk.BooleanVar(value=True)

        # Üst Frame: Dosya seç, dönüştür
        top_frame = tk.Frame(self)
        top_frame.pack(pady=5)

        self.btn_select = tk.Button(top_frame, text="PDF Seç", command=self.select_pdf)
        self.btn_select.pack(side=tk.LEFT, padx=5)

        self.btn_convert = tk.Button(top_frame, text="Dönüştür", command=self.start_conversion)
        self.btn_convert.pack(side=tk.LEFT, padx=5)

        # Ayar Frame
        settings_frame = tk.Frame(self)
        settings_frame.pack(pady=5)

        tk.Label(settings_frame, text="Chunk Size (kelime):").grid(row=0, column=0, sticky="e", padx=5)
        tk.Entry(settings_frame, textvariable=self.chunk_size_var, width=10).grid(row=0, column=1)

        tk.Label(settings_frame, text="Konuşma Hızı:").grid(row=1, column=0, sticky="e", padx=5)
        tk.Entry(settings_frame, textvariable=self.rate_var, width=10).grid(row=1, column=1)

        tk.Checkbutton(
            settings_frame,
            text="Parça MP3 dosyalarını finalden sonra sil",
            variable=self.clean_parts_var
        ).grid(row=2, columnspan=2, pady=5)

        # PDF Bilgisi
        self.file_label = tk.Label(self, text="Seçilen PDF: Henüz seçilmedi", wraplength=650)
        self.file_label.pack(pady=5)

        # Kalan süre için Label
        self.remaining_time_var = tk.StringVar(value="Kalan Süre: - ")
        self.remaining_time_label = tk.Label(self, textvariable=self.remaining_time_var, font=("Arial", 11, "bold"),
                                             fg="blue")
        self.remaining_time_label.pack(pady=5)

        # Log metni
        self.log_text = tk.Text(self, wrap=tk.WORD, height=15)
        self.log_text.pack(fill=tk.BOTH, expand=True)

        # Scrollbar
        scrollbar = tk.Scrollbar(self.log_text, command=self.log_text.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text.configure(yscrollcommand=scrollbar.set)

    def select_pdf(self):
        file_path = filedialog.askopenfilename(
            title="PDF Dosyası Seç",
            filetypes=[("PDF Files", "*.pdf"), ("All Files", "*.*")]
        )
        if file_path:
            self.pdf_path = file_path
            self.file_label.config(text=f"Seçilen PDF: {self.pdf_path}")
        else:
            self.file_label.config(text="Seçilen PDF: Henüz seçilmedi")

    def start_conversion(self):
        if not self.pdf_path:
            self.log("Lütfen önce bir PDF dosyası seçin!\n")
            return

        # Uzun işlem (dönüştürme) için thread
        t = threading.Thread(target=self.run_conversion)
        t.start()

    def run_conversion(self):
        # Arayüzdeki değerleri alalım
        chunk_size = self.chunk_size_var.get()
        rate = self.rate_var.get()
        clean_parts = self.clean_parts_var.get()

        try:
            pdf_to_mp3(
                pdf_path=self.pdf_path,
                chunk_size=chunk_size,
                rate=rate,
                clean_parts=clean_parts,
                log_callback=self.log,
                time_callback=self.update_remaining_time
            )
        except Exception as e:
            self.log(f"Hata: {e}")

    def log(self, message):
        self.log_text.insert(tk.END, message + "\n")
        self.log_text.see(tk.END)

    def update_remaining_time(self, time_text):
        self.remaining_time_var.set(time_text)


if __name__ == "__main__":
    app = PDFtoMP3App()
    app.mainloop()
