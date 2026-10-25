import { baseApi } from '@/shared/api'

export type Attachment = {
  id: number
  occurrence_id: number
  kind: 'file' | 'link'
  url: string | null
  title: string | null
  file_name: string | null
  content_type: 'image/jpeg' | 'image/png' | 'application/pdf' | null
  size_bytes: number | null
  created_at: string
  created_by: { id: number; login: string }
}

const attachmentApi = baseApi.injectEndpoints({
  endpoints: (builder) => ({
    getAttachments: builder.query<Attachment[], number>({
      query: (occurrenceId) => `payment-occurrences/${occurrenceId}/attachments`,
      providesTags: (_result, _error, occurrenceId) => [{ type: 'Attachments', id: occurrenceId }],
    }),
    addAttachmentLink: builder.mutation<Attachment, { occurrenceId: number; url: string; title: string | null }>({
      query: ({ occurrenceId, url, title }) => ({ url: `payment-occurrences/${occurrenceId}/attachments`, method: 'POST', body: { url, title } }),
      invalidatesTags: (_result, error, { occurrenceId }) => error ? [] : [{ type: 'Attachments', id: occurrenceId }, { type: 'Occurrences', id: occurrenceId }, 'Audit'],
    }),
    uploadAttachmentFile: builder.mutation<Attachment, { occurrenceId: number; file: File }>({
      query: ({ occurrenceId, file }) => {
        const body = new FormData()
        body.append('file', file)
        return { url: `payment-occurrences/${occurrenceId}/attachments`, method: 'POST', body }
      },
      invalidatesTags: (_result, error, { occurrenceId }) => error ? [] : [{ type: 'Attachments', id: occurrenceId }, { type: 'Occurrences', id: occurrenceId }, 'Audit'],
    }),
    downloadAttachmentFile: builder.mutation<string, number>({
      query: (id) => ({ url: `attachments/${id}/file`, responseHandler: (response: Response) => response.ok ? response.blob().then((blob) => URL.createObjectURL(blob)) : response.json() }),
    }),
    deleteAttachment: builder.mutation<void, { id: number; occurrenceId: number }>({
      query: ({ id }) => ({ url: `attachments/${id}`, method: 'DELETE' }),
      invalidatesTags: (_result, error, { occurrenceId }) => error ? [] : [{ type: 'Attachments', id: occurrenceId }, { type: 'Occurrences', id: occurrenceId }, 'Audit'],
    }),
  }),
})

export const { useGetAttachmentsQuery, useAddAttachmentLinkMutation, useUploadAttachmentFileMutation, useDownloadAttachmentFileMutation, useDeleteAttachmentMutation } = attachmentApi
