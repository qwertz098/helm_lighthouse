import { Editor } from '@tiptap/core'
import StarterKit from '@tiptap/starter-kit'
import Image from '@tiptap/extension-image'
import { Link } from '@tiptap/extension-link'
import { Placeholder } from '@tiptap/extension-placeholder'

// Expose on window so the page's inline module script can use them
window.TiptapEditor = Editor
window.TiptapStarterKit = StarterKit
window.TiptapImage = Image
window.TiptapLink = Link
window.TiptapPlaceholder = Placeholder
