import { useRef, useState } from "react";
import { api, type UploadResult } from "./api";

export default function Upload({ onChanged }: { onChanged: () => void }) {
  const input = useRef<HTMLInputElement>(null);
  const [results, setResults] = useState<UploadResult[]>([]);
  const [busy, setBusy] = useState(false);
  const [drag, setDrag] = useState(false);

  async function send(files: FileList | null) {
    if (!files?.length) return;
    setBusy(true);
    const done: UploadResult[] = [];
    for (const file of Array.from(files)) {
      try {
        done.push(await api.upload(file));
      } catch (e) {
        done.push({ filename: file.name, id: null, duplicate: false, bytes: -1 });
      }
    }
    setResults((r) => [...done, ...r]);
    setBusy(false);
    onChanged();
  }

  return (
    <div className="upload">
      <div
        className={`drop ${drag ? "over" : ""}`}
        onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
        onDragLeave={() => setDrag(false)}
        onDrop={(e) => { e.preventDefault(); setDrag(false); send(e.dataTransfer.files); }}
        onClick={() => input.current?.click()}
      >
        <strong>{busy ? "Uploading…" : "Drop claim PDFs here"}</strong>
        <span className="muted">or click to choose · multiple files are fine</span>
        <input
          ref={input}
          type="file"
          accept="application/pdf"
          multiple
          hidden
          onChange={(e) => send(e.target.files)}
        />
      </div>

      <p className="muted note">
        Uploading only queues the claim — it returns immediately. Extraction
        happens in a separate worker, so nothing here waits on a model call.
        Upload the same file twice and you get one claim: documents are named by
        content hash, so a repeat is the same object.
      </p>

      {results.length > 0 && (
        <table className="results">
          <tbody>
            {results.map((r, i) => (
              <tr key={i}>
                <td className="key">{r.filename}</td>
                <td>
                  {r.bytes < 0 ? (
                    <span className="tag bad">failed</span>
                  ) : r.duplicate ? (
                    <span className="tag warn">already submitted</span>
                  ) : (
                    <span className="tag good">queued</span>
                  )}
                </td>
                <td className="muted mono">{r.id ? r.id.slice(0, 8) : ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
