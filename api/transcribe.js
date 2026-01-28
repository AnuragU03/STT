const formidable = require("formidable");
const fs = require("fs");
const FormData = require("form-data");

const MAX_FILE_SIZE = 4 * 1024 * 1024; // 4MB (Vercel payload limit)
const ALLOWED_MIME_TYPES = "audio/";

module.exports = async function handler(req, res) {
    if (req.method !== "POST") {
        res.setHeader("Allow", "POST");
        return res.status(405).json({ detail: "Method not allowed" });
    }

    const apiKey = process.env.OPENAI_API_KEY;
    if (!apiKey) {
        return res.status(500).json({ detail: "OPENAI_API_KEY is not set" });
    }

    const form = formidable({
        multiples: false,
        maxFileSize: MAX_FILE_SIZE,
        keepExtensions: true,
    });

    try {
        const { files } = await new Promise((resolve, reject) => {
            form.parse(req, (err, fields, parsedFiles) => {
                if (err) {
                    reject(err);
                    return;
                }
                resolve({ fields, files: parsedFiles });
            });
        });

        const file = files.file;
        if (!file) {
            return res.status(400).json({ detail: "No file uploaded" });
        }

        const uploaded = Array.isArray(file) ? file[0] : file;
        if (!uploaded.mimetype || !uploaded.mimetype.startsWith(ALLOWED_MIME_TYPES)) {
            return res.status(400).json({
                detail: "Unsupported file type. Please upload an audio file",
            });
        }

        const formData = new FormData();
        formData.append("model", "whisper-1");
        formData.append("response_format", "verbose_json");
        formData.append("language", "en");
        formData.append("timestamp_granularities[]", "word");
        formData.append(
            "file",
            fs.createReadStream(uploaded.filepath),
            {
                filename: uploaded.originalFilename || "audio",
                contentType: uploaded.mimetype,
            }
        );

        const response = await fetch("https://api.openai.com/v1/audio/transcriptions", {
            method: "POST",
            headers: {
                Authorization: `Bearer ${apiKey}`,
                ...formData.getHeaders(),
            },
            body: formData,
        });

        const data = await response.json();
        if (!response.ok) {
            return res.status(response.status).json({ detail: data.error?.message || "Transcription failed" });
        }

        const words = Array.isArray(data.words)
            ? data.words.map((w) => ({
                  word: w.word,
                  start: Number(w.start),
                  end: Number(w.end),
              }))
            : [];

        return res.status(200).json({
            transcription: data.text || "",
            words,
        });
    } catch (err) {
        const message = err?.message || "Transcription failed";
        return res.status(500).json({ detail: message });
    }
};

module.exports.config = {
    api: {
        bodyParser: false,
    },
};
