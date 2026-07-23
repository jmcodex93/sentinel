import { Plus, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { Button } from "../components/form/Button";
import { FieldRow } from "../components/form/FieldRow";
import { FormPageShell } from "../components/form/FormPageShell";
import { SubmitBar } from "../components/form/SubmitBar";
import { TextArea } from "../components/form/TextArea";
import { TextInput } from "../components/form/TextInput";
import { EmptyState, ErrorState, LoadingState } from "../components/PageStates";
import { fetchNotesState, submitNotes } from "../lib/api";
import { useToast } from "../lib/toast";
import type { NotesState, NotesStateResult, NotesTodo } from "../types";

type PageState = { kind: "loading" } | NotesStateResult;

/** A TODO the SPA is editing — `key` is a stable React list key distinct
 * from `id` (which is null for a not-yet-saved TODO; several can be null at
 * once, so `id` alone can't key the list). Never sent to the server. */
interface EditableTodo extends NotesTodo {
  key: string;
}

let localKeySeq = 0;
function nextKey(): string {
  localKeySeq += 1;
  return `local-${localKeySeq}`;
}

function toEditable(todos: NotesTodo[]): EditableTodo[] {
  return todos.map((todo) => ({ ...todo, key: todo.id !== null ? `id-${todo.id}` : nextKey() }));
}

/** Scene Notes & TODOs — mirrors `ui/dialogs.py` `NotesDialog` (see
 * web_ops.py `_op_form_notes_state/_submit`'s docstrings): free-form notes
 * shared across every version of this scene base, plus a TODO checklist
 * (add/toggle/delete — the native dialog never supported editing existing
 * TODO text either, see `merge_notes_submission`'s docstring).
 *
 * `onBack`/`onDone` are optional — absent when hosted one-per-window by
 * `FormDialog` (unchanged behavior), present when absorbed as an in-panel
 * sub-view by the Deliver section (Fase 6.3 Task 5): `onBack` renders a
 * "← Deliver" control, `onDone` fires after a successful save. */
export function NotesPage({
  onBack,
  onDone,
}: { onBack?: () => void; onDone?: () => void } = {}) {
  const { toast } = useToast();
  const [state, setState] = useState<PageState>({ kind: "loading" });
  const [notesText, setNotesText] = useState("");
  const [todos, setTodos] = useState<EditableTodo[]>([]);
  const [newTodoText, setNewTodoText] = useState("");
  const [pending, setPending] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  const load = useCallback(() => {
    setState({ kind: "loading" });
    fetchNotesState().then((result) => {
      setState(result);
      if (result.kind === "ok") {
        setNotesText(result.data.notes_text);
        setTodos(toEditable(result.data.todos));
      }
    });
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  if (state.kind === "loading") return <LoadingState />;
  if (state.kind === "error") {
    return <ErrorState title="Couldn't load Notes" message={state.message} onRetry={load} />;
  }
  if (state.kind === "empty") {
    return <EmptyState title="Scene not saved" reason={state.reason} />;
  }

  const data: NotesState = state.data;
  const pendingCount = todos.filter((todo) => !todo.done).length;

  function addTodo() {
    const text = newTodoText.trim();
    if (!text) return;
    setTodos((prev) => [...prev, { key: nextKey(), id: null, text, done: false }]);
    setNewTodoText("");
  }

  function toggleTodo(key: string) {
    setTodos((prev) => prev.map((todo) => (todo.key === key ? { ...todo, done: !todo.done } : todo)));
  }

  function deleteTodo(key: string) {
    setTodos((prev) => prev.filter((todo) => todo.key !== key));
  }

  async function handleSubmit() {
    setSubmitError(null);
    setPending(true);
    const response = await submitNotes({
      notes_text: notesText,
      todos: todos.map((todo) => ({ id: todo.id, text: todo.text, done: todo.done })),
    });
    setPending(false);

    if (!response.ok) {
      setSubmitError(response.error || "Failed to save notes.");
      return;
    }
    toast({ message: "Notes saved.", variant: "success" });
    load(); // re-sync ids the server assigned to newly added TODOs
    onDone?.();
  }

  return (
    <FormPageShell
      embedded={Boolean(onBack)}
      title="Scene Notes"
      meta={
        <p className="text-caption mt-1.5" style={{ color: "var(--color-ink-secondary)" }}>
          {data.scene_base} · shared across all versions of this scene
        </p>
      }
      footer={<SubmitBar submitLabel="Save Notes" pending={pending} onSubmit={handleSubmit} error={submitError} />}
    >
      {onBack && (
        <Button variant="secondary" className="mb-3" onClick={onBack}>
          ← Deliver
        </Button>
      )}
      <div className="flex flex-col gap-4">
        <FieldRow label="Notes" htmlFor="notes-text">
          <TextArea
            id="notes-text"
            rows={6}
            value={notesText}
            onChange={(e) => setNotesText(e.target.value)}
            placeholder="Free-form notes about this scene…"
          />
        </FieldRow>

        <FieldRow label={`TODOs${pendingCount ? ` (${pendingCount} pending)` : ""}`}>
          <div className="flex flex-col gap-2">
            {todos.length === 0 && (
              <p className="text-caption" style={{ color: "var(--color-ink-secondary)" }}>
                No TODOs yet.
              </p>
            )}
            {todos.map((todo) => (
              <div
                key={todo.key}
                className="flex items-center gap-2 rounded-md border px-2 py-1.5"
                style={{ borderColor: "var(--color-hairline)", backgroundColor: "var(--color-surface-1)" }}
              >
                <input
                  type="checkbox"
                  checked={todo.done}
                  onChange={() => toggleTodo(todo.key)}
                  style={{ accentColor: "var(--color-primary)" }}
                  aria-label={todo.done ? `Mark "${todo.text}" as not done` : `Mark "${todo.text}" as done`}
                />
                <span
                  className="text-body flex-1"
                  style={{
                    color: todo.done ? "var(--color-muted)" : "var(--color-ink)",
                    textDecoration: todo.done ? "line-through" : "none",
                  }}
                >
                  {todo.text}
                </span>
                <button
                  type="button"
                  onClick={() => deleteTodo(todo.key)}
                  aria-label={`Delete "${todo.text}"`}
                  className="shrink-0 rounded-sm p-1 transition-colors duration-100 ease-out hover:bg-[var(--color-surface-2)]"
                >
                  <Trash2 size={14} strokeWidth={2.25} style={{ color: "var(--color-ink-secondary)" }} aria-hidden="true" />
                </button>
              </div>
            ))}
            <div className="flex items-center gap-2">
              <TextInput
                value={newTodoText}
                onChange={(e) => setNewTodoText(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    addTodo();
                  }
                }}
                placeholder="Add a TODO…"
              />
              <Button onClick={addTodo}>
                <Plus size={14} strokeWidth={2.25} aria-hidden="true" />
                Add
              </Button>
            </div>
          </div>
        </FieldRow>
      </div>
    </FormPageShell>
  );
}
