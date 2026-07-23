import { NativeDialog } from './NativeDialog'

export function NoticeDialog({ title, message, close }: { title: string; message: string; close: () => void }) {
  return <NativeDialog title={title} close={close}>
    <div className="notice-dialog-content">
      <p>{message}</p>
      <div className="modal-actions">
        <button className="primary" onClick={close}>OK</button>
      </div>
    </div>
  </NativeDialog>
}
