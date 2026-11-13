import { useCallback, useEffect, useState } from 'react'
import './App.css'

const API_BASE = import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000/api'
const API = `${API_BASE}/vendor/applications/${localStorage.getItem('vf_application_ref') || ''}`

function App() {
  const [activePage, setActivePage] = useState('Dashboard')
  const [saved, setSaved] = useState(false)

  const [profile, setProfile] = useState({
    company_name: '',
    business_type: '',
    email: '',
    phone: '',
    address_line1: '',
    city: '',
    state: '',
    postal_code: '',
    country: 'India',
    authorised_rep_name: '',
    authorised_rep_designation: '',
  })

  const [documents, setDocuments] = useState([])
  const [extractionDrafts, setExtractionDrafts] = useState({})
  const [extractionAppliedMessage, setExtractionAppliedMessage] = useState('')
  const [uploadingSlot, setUploadingSlot] = useState('')
  const [deletingSlot, setDeletingSlot] = useState('')
  const [authLetterSlotId, setAuthLetterSlotId] = useState('')
  const [applicationDetails, setApplicationDetails] = useState(null)
  const [statusRefreshing, setStatusRefreshing] = useState(false)

  const [actionData, setActionData] = useState(null)
  const [actionLoading, setActionLoading] = useState(false)
  const [actionError, setActionError] = useState('')

  const [pendingDocumentSlot, setPendingDocumentSlot] = useState('')
  const [pendingProfileField, setPendingProfileField] = useState('')
  const [pendingTaxField, setPendingTaxField] = useState('')

  const [taxDraft, setTaxDraft] = useState({
    pan: '',
    cin: '',
    gstin: '',
    gstinStatus: '',
    gstinReason: '',
  })

  const [taxInfo, setTaxInfo] = useState({
    panMasked: '',
    cinMasked: '',
    gstinMasked: '',
    gstinStatus: '',
    gstinReason: '',
  })

  const [bankDraft, setBankDraft] = useState({
    ifsc: '',
    accountNumber: '',
    holderName: '',
    accountRelationship: 'same_legal_entity',
    relationshipExplanation: '',
  })

  const [bankInfo, setBankInfo] = useState({
    accountId: 'acct-demo-1',
    bankName: '',
    accountHolder: '',
    maskedAccountNumber: '',
    ifsc: '',
  })

  const [pendingBankField, setPendingBankField] = useState('')
  const [bankSaving, setBankSaving] = useState(false)

  const [presubmitResult, setPresubmitResult] = useState(null)
  const [presubmitLoading, setPresubmitLoading] = useState(false)
  const [declarationAccepted, setDeclarationAccepted] = useState(false)
  const [submittingApplication, setSubmittingApplication] = useState(false)
  const [submissionResult, setSubmissionResult] = useState(null)
  const [submissionError, setSubmissionError] = useState('')
  const [validationResult, setValidationResult] = useState(null)
  const [validationLoading, setValidationLoading] = useState(false)
  const [validationError, setValidationError] = useState('')

  const menuItems = [
    { icon: '⌂', label: 'Dashboard' },
    { icon: '▤', label: 'Company Profile' },
    { icon: '▥', label: 'Tax Registrations' },
    { icon: '▣', label: 'Bank Accounts' },
    { icon: '▧', label: 'Documents' },
    { icon: '◎', label: 'Validation' },
    { icon: '◷', label: 'Application Status' },
    { icon: '✓', label: 'Review & Submit' },
    { icon: '⚑', label: 'Action Required' },
  ]

  // Load the application and populate the profile and registration summaries.
  const loadApplication = useCallback(async () => {
    const response = await fetch(API)

    if (!response.ok) {
      throw new Error('Could not load application details')
    }

    const result = await response.json()
    const submission = result.submission || {}
    const savedProfile = submission.profile || {}

    // Discover the account-specific authorisation slot from the backend.
    try {
      const requirementsResponse = await fetch(`${API}/requirements`)
      if (requirementsResponse.ok) {
        const requirements = await requirementsResponse.json()
        const authSlot = (requirements.slots || []).find(
          (slot) =>
            slot.doc_type === 'AUTH_LETTER' &&
            String(slot.slot_id || '').startsWith('bank_auth:')
        )
        setAuthLetterSlotId(authSlot?.slot_id || '')
      }
    } catch (requirementsError) {
      console.error('Could not load document requirements:', requirementsError)
    }

    setApplicationDetails(result)
    setDocuments(submission.documents || [])
    setExtractionDrafts(Object.fromEntries((submission.documents || []).map((document) => {
      const fields = document.extracted_fields || {}
      const firstValue = (value) => Array.isArray(value) ? (value[0] || '') : (value ?? '')
      return [document.slot_id, {
        legal_name: String(firstValue(fields.legal_name)),
        pan: String(firstValue(fields.pan)),
        gstin: String(firstValue(fields.gstin)),
        cin: String(firstValue(fields.cin)),
      }]
    })))

    const businessTypes = {
      private_limited: 'Private Limited',
      public_limited: 'Public Limited',
      llp: 'LLP',
      partnership: 'Partnership',
      sole_proprietorship: 'Proprietorship',
      other: 'Other',
    }

    setProfile((previous) => ({
      ...previous,
      company_name: savedProfile.legal_name || '',
      business_type:
        businessTypes[savedProfile.entity_type] || 'Other',
      email: savedProfile.contact_email || '',
      authorised_rep_name:
        savedProfile.authorised_rep?.name || '',
      authorised_rep_designation:
        savedProfile.authorised_rep?.designation || '',
      address_line1:
        savedProfile.registered_address?.line1 || '',
      city: savedProfile.registered_address?.city || '',
      state: savedProfile.registered_address?.state || '',
      postal_code:
        savedProfile.registered_address?.postcode || '',
      country:
        savedProfile.registered_address?.country || 'IN',
    }))

    // These values are masked by the backend.
    // They are for display only and are never sent back as corrections.
    const registrations = submission.tax_registrations || []

    const pan = registrations.find((item) => item.type === 'PAN')
    const cin = registrations.find((item) => item.type === 'CIN')
    const gstin = registrations.find((item) => item.type === 'GSTIN')

    setTaxInfo({
      panMasked: pan?.value || '',
      cinMasked: cin?.value || '',
      gstinMasked: gstin?.value || '',
      gstinStatus: gstin?.status || '',
      gstinReason: gstin?.status_reason || '',
    })

    setTaxDraft((previous) => ({
      ...previous,
      gstinStatus: gstin?.status || '',
      gstinReason: gstin?.status_reason || '',
    }))

    // Bank account numbers are masked by the backend. Keep the masked
    // value for display only; never use it to prefill the correction input.
    const bankAccount = (submission.bank_accounts || []).find(
      (item) => item.id === 'acct-demo-1'
    )

    setBankInfo({
      accountId: bankAccount?.id || 'acct-demo-1',
      bankName: bankAccount?.bank_name || bankAccount?.bankName || '',
      accountHolder:
        bankAccount?.holder_name ||
        bankAccount?.account_holder ||
        bankAccount?.account_holder_name ||
        bankAccount?.accountHolder ||
        '',
      maskedAccountNumber: bankAccount?.account_number || '',
      ifsc: bankAccount?.identifier || '',
    })

    setBankDraft((previous) => ({
      ...previous,
      holderName:
        bankAccount?.holder_name ||
        bankAccount?.account_holder_name ||
        bankAccount?.account_holder ||
        '',
      accountRelationship:
        bankAccount?.account_relationship || 'same_legal_entity',
      relationshipExplanation:
        bankAccount?.account_relationship_explanation || '',
    }))

    return result
  }, [])

  useEffect(() => {
    loadApplication().catch((error) => {
      console.error('Application loading error:', error)
    })
  }, [loadApplication])

  function handleChange(event) {
    const { name, value } = event.target

    setProfile((previous) => ({
      ...previous,
      [name]: value,
    }))

    setSaved(false)
  }

  async function handleSave(event) {
    event.preventDefault()
    setSaved(false)

    const entityTypes = {
      'Private Limited': 'private_limited',
      'Public Limited': 'public_limited',
      LLP: 'llp',
      Partnership: 'partnership',
      Proprietorship: 'sole_proprietorship',
      Other: 'other',
    }

    const payload = {
      section: 'profile',
      data: {
        country: 'IN',
        legal_name: profile.company_name,
        entity_type: entityTypes[profile.business_type] || 'other',
        contact_email: profile.email,

        authorised_rep: {
          name: profile.authorised_rep_name,
          designation: profile.authorised_rep_designation,
        },

        registered_address: {
          line1: profile.address_line1,
          city: profile.city,
          state: profile.state,
          postcode: profile.postal_code,
          country: 'IN',
        },
      },
    }

    try {
      const response = await fetch(`${API}/draft`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(payload),
      })

      const result = await response.json()

      if (!response.ok) {
        throw new Error(result.detail || 'Unable to save profile')
      }

      setSaved(true)
      alert('Company profile saved successfully!')
    } catch (error) {
      console.error('Save error:', error)
      alert('Could not save: ' + error.message)
    }
  }

  function handleTaxChange(event) {
    const { name, value } = event.target

    setTaxDraft((previous) => ({
      ...previous,
      [name]: value,
    }))
  }

  // Save only the registration types that the vendor actually changed.
  // The backend merges these updates with the existing registration list.
  async function handleTaxSave(event) {
    event.preventDefault()

    const updates = []

    if (taxDraft.pan.trim()) {
      updates.push({
        type: 'PAN',
        jurisdiction: 'IN',
        value: taxDraft.pan.trim().toUpperCase(),
      })
    }

    if (taxDraft.cin.trim()) {
      updates.push({
        type: 'CIN',
        jurisdiction: 'IN',
        value: taxDraft.cin.trim().toUpperCase(),
      })
    }

    if (taxDraft.gstinStatus === 'registered') {
      if (!taxDraft.gstin.trim()) {
        alert('Please enter the GSTIN before saving a registered status.')
        return
      }

      updates.push({
        type: 'GSTIN',
        jurisdiction: 'IN',
        value: taxDraft.gstin.trim().toUpperCase(),
        status: 'registered',
        status_reason: '',
      })
    } else if (taxDraft.gstinStatus === 'not_registered') {
      if (!taxDraft.gstinReason.trim()) {
        alert('Please provide a reason for not being GST registered.')
        return
      }

      updates.push({
        type: 'GSTIN',
        jurisdiction: 'IN',
        status: 'not_registered',
        status_reason: taxDraft.gstinReason.trim(),
      })
    }

    if (updates.length === 0) {
      alert('Enter at least one correction or select your GSTIN status.')
      return
    }

    try {
      const response = await fetch(`${API}/draft`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          section: 'tax_registration_updates',
          data: {
            registrations: updates,
          },
        }),
      })

      const result = await response.json()

      if (!response.ok) {
        throw new Error(
          result.detail || 'Unable to save tax registrations'
        )
      }

      setTaxDraft({
        pan: '',
        cin: '',
        gstin: '',
        gstinStatus: taxDraft.gstinStatus,
        gstinReason: taxDraft.gstinReason,
      })

      await loadApplication()

      alert('Tax registration updates saved successfully!')
    } catch (error) {
      console.error('Tax registration save error:', error)
      alert('Could not save tax registrations: ' + error.message)
    }
  }

  function renderTaxRegistrations() {
    return (
      <section className="panel profile-panel">
        <div className="panel-heading">
          <div>
            <h3>Tax registrations</h3>
            <p>
              Review and correct your company's tax registration details.
            </p>
          </div>
          <span className="small-tag">Tax information</span>
        </div>

        <form onSubmit={handleTaxSave}>
          <div
            className="form-section-title"
            id="pan-correction-section"
          >
            Permanent Account Number (PAN)
          </div>

          <p className="stat-note">
            Current saved value: {taxInfo.panMasked || 'No PAN recorded'}.
            Enter a new value only if a correction is required.
          </p>

          <div className="form-grid">
            <label className="form-field full-field">
              Correct PAN
              <input
                id="tax-pan-input"
                name="pan"
                value={taxDraft.pan}
                onChange={handleTaxChange}
                placeholder="Enter corrected PAN"
                maxLength={10}
                autoComplete="off"
              />
            </label>
          </div>

          <div
            className="form-section-title"
            id="cin-correction-section"
          >
            Corporate Identification Number (CIN)
          </div>

          <p className="stat-note">
            Current saved value: {taxInfo.cinMasked || 'No CIN recorded'}.
            Enter a new value only if a correction is required.
          </p>

          <div className="form-grid">
            <label className="form-field full-field">
              Correct CIN
              <input
                id="tax-cin-input"
                name="cin"
                value={taxDraft.cin}
                onChange={handleTaxChange}
                placeholder="Enter corrected CIN"
                maxLength={21}
                autoComplete="off"
              />
            </label>
          </div>

          <div
            className="form-section-title"
            id="gstin-status-section"
          >
            GSTIN registration status
          </div>

          <p className="stat-note">
            Current status: {taxInfo.gstinStatus || 'Not declared'}
            {taxInfo.gstinMasked
              ? ` · Saved value: ${taxInfo.gstinMasked}`
              : ''}
          </p>

          <div className="form-grid">
            <label className="form-field">
              Are you registered under GST? *
              <select
                id="gstin-status-select"
                name="gstinStatus"
                value={taxDraft.gstinStatus}
                onChange={handleTaxChange}
                required
              >
                <option value="">Select status</option>
                <option value="registered">Registered</option>
                <option value="not_registered">Not registered</option>
              </select>
            </label>

            {taxDraft.gstinStatus === 'registered' && (
              <label className="form-field">
                GSTIN *
                <input
                  id="tax-gstin-input"
                  name="gstin"
                  value={taxDraft.gstin}
                  onChange={handleTaxChange}
                  placeholder="Enter GSTIN"
                  maxLength={15}
                  required
                  autoComplete="off"
                />
              </label>
            )}

            {taxDraft.gstinStatus === 'not_registered' && (
              <label className="form-field full-field">
                Reason for not being GST registered *
                <textarea
                  id="gstin-reason-input"
                  name="gstinReason"
                  value={taxDraft.gstinReason}
                  onChange={handleTaxChange}
                  placeholder="Explain why your business is not registered under GST"
                  rows={3}
                  required
                />
              </label>
            )}
          </div>

          <div className="form-actions">
            <button
              type="submit"
              className="primary-button save-button"
            >
              Save Tax Details
            </button>
          </div>
        </form>
      </section>
    )
  }

  function handleBankChange(event) {
    const { name, value } = event.target
    setBankDraft((previous) => ({
      ...previous,
      [name]: value,
    }))
  }

  async function handleBankSave(event) {
    event.preventDefault()

    const ifsc = bankDraft.ifsc.trim().toUpperCase()
    const accountNumber = bankDraft.accountNumber.trim()
    const holderName = bankDraft.holderName.trim()
    const accountRelationship = bankDraft.accountRelationship
    const relationshipExplanation =
      bankDraft.relationshipExplanation.trim()

    if (!holderName) {
      alert('Please enter the account holder name exactly as shown on the bank evidence.')
      return
    }

    if (
      accountRelationship !== 'same_legal_entity' &&
      !relationshipExplanation
    ) {
      alert('Please explain the declared bank account ownership relationship.')
      return
    }

    const accountUpdate = {
      id: bankInfo.accountId || 'acct-demo-1',
      holder_name: holderName,
      account_relationship: accountRelationship,
    }

    if (ifsc) accountUpdate.identifier = ifsc
    if (accountNumber) accountUpdate.account_number = accountNumber

    if (relationshipExplanation) {
      accountUpdate.account_relationship_explanation = relationshipExplanation
    } else if (accountRelationship === 'same_legal_entity') {
      accountUpdate.account_relationship_explanation = 'Same legal entity'
    }

    setBankSaving(true)

    try {
      const response = await fetch(`${API}/draft`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          section: 'bank_account_updates',
          data: {
            accounts: [accountUpdate],
          },
        }),
      })

      const result = await response.json()

      if (!response.ok) {
        throw new Error(
          typeof result.detail === 'string'
            ? result.detail
            : 'Unable to save bank account details'
        )
      }

      setBankDraft((previous) => ({
        ...previous,
        ifsc: '',
        accountNumber: '',
      }))

      await loadApplication()
      alert('Bank account details and ownership declaration saved successfully!')
    } catch (error) {
      console.error('Bank account save error:', error)
      alert('Could not save bank account details: ' + error.message)
    } finally {
      setBankSaving(false)
    }
  }

  function renderBankAccounts() {
    return (
      <section className="panel profile-panel">
        <div className="panel-heading">
          <div>
            <h3>Bank account details</h3>
            <p>
              Review the saved bank account and provide corrections requested
              by the onboarding team.
            </p>
          </div>
          <span className="small-tag">Bank information</span>
        </div>

        <div className="form-section-title">Primary bank account</div>

        <div className="document-item">
          <div>
            <strong>{bankInfo.bankName || 'Bank name not available'}</strong>
            <p>
              Account holder: {bankInfo.accountHolder || 'Not available'}
            </p>
            <p>
              Account number: {bankInfo.maskedAccountNumber || 'Not available'}
            </p>
            <p>Current IFSC: {bankInfo.ifsc || 'Not available'}</p>
          </div>
          <span className="small-tag">Account reference</span>
        </div>

        <p className="stat-note">
          For security, the saved account number is masked. The correction
          fields below are intentionally blank. Enter a value only if a
          correction is required.
        </p>

        <form onSubmit={handleBankSave}>
          <div className="form-section-title" id="ifsc-correction-section">
            IFSC code correction
          </div>

          <div className="form-grid">
            <label className="form-field full-field">
              Correct IFSC code
              <input
                id="bank-ifsc-input"
                name="ifsc"
                value={bankDraft.ifsc}
                onChange={handleBankChange}
                placeholder="Enter corrected IFSC code"
                maxLength={11}
                autoComplete="off"
                style={{ textTransform: 'uppercase' }}
              />
            </label>
          </div>

          <div
            className="form-section-title"
            id="account-number-correction-section"
          >
            Bank account number correction
          </div>

          <div className="form-grid">
            <label className="form-field full-field">
              Correct account number
              <input
                id="bank-account-number-input"
                name="accountNumber"
                type="password"
                inputMode="numeric"
                value={bankDraft.accountNumber}
                onChange={handleBankChange}
                placeholder="Enter corrected account number"
                autoComplete="new-password"
              />
            </label>
          </div>

          <div className="form-section-title" id="bank-ownership-section">
            Bank account ownership declaration
          </div>

          <div className="form-grid">
            <label className="form-field full-field">
              Account holder name (as shown on bank evidence) *
              <input
                id="bank-holder-name-input"
                name="holderName"
                value={bankDraft.holderName}
                onChange={handleBankChange}
                placeholder="Enter the exact account holder name"
                autoComplete="off"
                required
              />
            </label>
          </div>

          <p className="stat-note">
            Tell us how the bank account is related to the legal business.
            If the account holder is not the same legal entity, provide an explanation
            and upload the relevant authorisation evidence in the Documents section.
          </p>

          <div className="form-grid">
            <label className="form-field full-field">
              Account holder relationship *
              <select
                id="bank-account-relationship"
                name="accountRelationship"
                value={bankDraft.accountRelationship}
                onChange={handleBankChange}
                required
              >
                <option value="same_legal_entity">Same legal entity</option>
                <option value="sole_proprietor">Sole proprietor</option>
                <option value="director_authorised_individual">
                  Director / Authorised Individual
                </option>
                <option value="related_party">Related party</option>
                <option value="joint">Joint account</option>
                <option value="other">Other</option>
              </select>
            </label>

            {bankDraft.accountRelationship !== 'same_legal_entity' && (
              <label className="form-field full-field">
                Explain the account ownership relationship *
                <textarea
                  id="bank-relationship-explanation"
                  name="relationshipExplanation"
                  value={bankDraft.relationshipExplanation}
                  onChange={handleBankChange}
                  placeholder="Explain who owns the account and their relationship to the business."
                  rows={4}
                  required
                />
              </label>
            )}
          </div>

          <div className="form-actions">
            <button
              type="submit"
              className="primary-button save-button"
              disabled={bankSaving}
            >
              {bankSaving ? 'Saving...' : 'Save Bank Details'}
            </button>
          </div>
        </form>
      </section>
    )
  }

  async function handleDocumentUpload(slotId, event) {
    const file = event.target.files?.[0]

    if (!file) return

    const formData = new FormData()
    formData.append('file', file)

    setUploadingSlot(slotId)

    try {
      const response = await fetch(
        `${API}/documents/${encodeURIComponent(slotId)}`,
        {
          method: 'POST',
          body: formData,
        }
      )

      const result = await response.json()

      if (!response.ok) {
        const message =
          typeof result.detail === 'string'
            ? result.detail
            : 'Unable to upload document'

        throw new Error(message)
      }

      await loadApplication()
      alert('Document uploaded successfully!')
    } catch (error) {
      console.error('Document upload error:', error)
      alert('Could not upload document: ' + error.message)
    } finally {
      setUploadingSlot('')
      event.target.value = ''
    }
  }

  async function handleDeleteDocument(slotId, documentTitle) {
    const confirmed = window.confirm(
      `Remove the uploaded ${documentTitle}? This will also clear any linked bank authorisation evidence.`
    )
    if (!confirmed) return

    setDeletingSlot(slotId)
    try {
      const response = await fetch(
        `${API}/documents/${encodeURIComponent(slotId)}`,
        { method: 'DELETE' }
      )
      const result = await response.json()
      if (!response.ok) {
        const message =
          typeof result.detail === 'string'
            ? result.detail
            : 'Unable to remove document'
        throw new Error(message)
      }

      await loadApplication()
      setPresubmitResult(null)
      alert('Document removed successfully.')
    } catch (error) {
      console.error('Document delete error:', error)
      alert('Could not remove document: ' + error.message)
    } finally {
      setDeletingSlot('')
    }
  }

  async function handleRunPresubmit() {
    setPresubmitLoading(true)
    setSubmissionError('')
    setSubmissionResult(null)

    try {
      const response = await fetch(`${API}/presubmit`, {
        method: 'POST',
      })
      const result = await response.json()

      if (!response.ok) {
        throw new Error(
          typeof result.detail === 'string'
            ? result.detail
            : 'Unable to validate application readiness'
        )
      }

      setPresubmitResult(result)
      setDeclarationAccepted(false)
      await loadApplication()
    } catch (error) {
      console.error('Pre-submission validation error:', error)
      setSubmissionError(error.message)
    } finally {
      setPresubmitLoading(false)
    }
  }

  async function handleFinalSubmit(event) {
    event.preventDefault()

    if (!declarationAccepted) {
      setSubmissionError('Please accept the vendor declaration before submitting.')
      return
    }

    setSubmittingApplication(true)
    setSubmissionError('')
    setSubmissionResult(null)

    try {
      // Always perform a fresh readiness check immediately before submission.
      const readinessResponse = await fetch(`${API}/presubmit`, {
        method: 'POST',
      })
      const readiness = await readinessResponse.json()

      if (!readinessResponse.ok) {
        throw new Error(
          typeof readiness.detail === 'string'
            ? readiness.detail
            : 'Could not verify application readiness'
        )
      }

      setPresubmitResult(readiness)

      if (!readiness.ready || (readiness.blockers || []).length > 0) {
        setDeclarationAccepted(false)
        setSubmissionError(
          'Your application is not ready. Resolve the blockers listed below and check readiness again.'
        )
        return
      }

      const response = await fetch(`${API}/submit`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          accepted: true,
          version: 'v1',
          actor: 'vendor',
        }),
      })

      const result = await response.json()

      if (!response.ok) {
        const detail = result.detail
        throw new Error(
          typeof detail === 'string'
            ? detail
            : detail?.blockers?.join(' · ') || 'Application submission failed'
        )
      }

      setSubmissionResult(result)
      setDeclarationAccepted(false)
      await loadApplication()
    } catch (error) {
      console.error('Application submission error:', error)
      setSubmissionError(error.message)
    } finally {
      setSubmittingApplication(false)
    }
  }

  async function handleRunValidation() {
    setValidationLoading(true)
    setValidationError('')
    try {
      const response = await fetch(`${API}/validate`, { method: 'POST' })
      const result = await response.json()
      if (!response.ok) {
        throw new Error(typeof result.detail === 'string' ? result.detail : 'Unable to run validation')
      }
      setValidationResult(result)
    } catch (error) {
      setValidationError(error.message)
    } finally {
      setValidationLoading(false)
    }
  }

  function renderValidation() {
    const findings = validationResult?.findings || []
    const summary = validationResult?.summary || {}
    const grouped = findings.reduce((groups, finding) => {
      const key = finding.severity || 'info'
      groups[key] = [...(groups[key] || []), finding]
      return groups
    }, {})
    const statusColor = (status) => status === 'pass' ? '#16845b' : status === 'mismatch' || status === 'missing' ? '#c44747' : '#a66a12'

    return (
      <section className="panel profile-panel">
        <div className="panel-heading">
          <div>
            <h3>Intelligent validation</h3>
            <p>Check identifier formats, cross-document consistency, bank-holder names, duplicate files and required documents.</p>
          </div>
          <span className="small-tag">Release 1</span>
        </div>
        <p className="stat-note">Run these checks after updating company details or uploading documents. OCR candidates are compared with saved details but are not proof of identity.</p>
        <div className="form-actions">
          <button type="button" className="primary-button" onClick={handleRunValidation} disabled={validationLoading}>
            {validationLoading ? 'Running checks...' : 'Run validation checks'}
          </button>
        </div>
        {validationError && <div className="alert-item" role="alert"><span>!</span><div><strong>Validation could not run</strong><p>{validationError}</p></div></div>}
        {validationResult && (
          <>
            <div className="document-item" style={{ marginTop: 18 }}>
              <div>
                <strong>{validationResult.overall_status.replaceAll('_', ' ')}</strong>
                <p>Validation run for version {validationResult.version} · {new Date(validationResult.created_at).toLocaleString()}</p>
              </div>
              <span className="small-tag">{summary.total || 0} checks</span>
            </div>
            <div className="stats-grid" style={{ marginTop: 14 }}>
              <div className="stat-card"><span className="stat-label">PASSED</span><h2>{summary.passed || 0}</h2></div>
              <div className="stat-card"><span className="stat-label">BLOCKERS</span><h2>{summary.blockers || 0}</h2></div>
              <div className="stat-card"><span className="stat-label">REVIEW ITEMS</span><h2>{summary.review_items || 0}</h2></div>
              <div className="stat-card"><span className="stat-label">MISSING</span><h2>{summary.missing || 0}</h2></div>
            </div>
            {['blocker', 'review', 'info'].map((severity) => grouped[severity]?.length > 0 && (
              <div key={severity}>
                <div className="form-section-title">{severity === 'info' ? 'Passed and informational checks' : severity === 'blocker' ? 'Blocking issues' : 'Needs reviewer attention'}</div>
                <div className="document-list">
                  {grouped[severity].map((finding, index) => (
                    <div className="document-item" key={`${finding.code}-${index}`}>
                      <div style={{ minWidth: 0 }}>
                        <strong>{finding.field}</strong>
                        <p>{finding.message}</p>
                        {finding.action && <p className="stat-note">Next step: {finding.action}</p>}
                        <p className="stat-note">Rule: {finding.code} · Source: {finding.source}</p>
                      </div>
                      <span className="small-tag" style={{ color: statusColor(finding.status), whiteSpace: 'nowrap' }}>{finding.status.replaceAll('_', ' ')}</span>
                    </div>
                  ))}
                </div>
              </div>
            ))}
            <div className="form-section-title">Important limitations</div>
            <ul>{(validationResult.limitations || []).map((item, index) => <li key={index}>{item}</li>)}</ul>
          </>
        )}
        {!validationResult && !validationError && <p className="stat-note">No validation run has been performed for this application yet.</p>}
      </section>
    )
  }

  function renderReviewSubmit() {
    const requiredDocuments = [
      { id: 'pan_card', label: 'PAN Card' },
      { id: 'incorporation_cert', label: 'Incorporation Certificate' },
      { id: 'bank_evidence:acct-demo-1', label: 'Bank Evidence' },
      { id: 'gst_cert', label: 'GST Registration Certificate' },
    ]
    const uploadedSlotIds = new Set(documents.map((item) => item.slot_id))
    const blockers = presubmitResult?.blockers || []
    const warnings = presubmitResult?.warnings || []
    const reviewItems = presubmitResult?.review_items || []
    const currentState = applicationDetails?.state || ''
    const alreadySubmitted = ['PROCESSING', 'APPROVED', 'REJECTED'].includes(
      currentState
    )

    return (
      <section className="panel profile-panel">
        <div className="panel-heading">
          <div>
            <h3>Review your application</h3>
            <p>
              Check your saved information and required documents before final submission.
            </p>
          </div>
          <span className="small-tag">Final review</span>
        </div>

        <div className="form-section-title">Application summary</div>
        <div className="document-item">
          <div>
            <strong>{applicationDetails?.application_ref || localStorage.getItem('vf_application_ref') || 'New application'}</strong>
            <p>Application reference</p>
            <p>Current version: {applicationDetails?.version ?? 'Loading...'}</p>
            <p>Current state: {currentState || 'Loading...'}</p>
          </div>
          <span className="small-tag">Vendor application</span>
        </div>

        <div className="form-section-title">Required document checklist</div>
        <div className="document-list">
          {requiredDocuments.map((document) => {
            const uploaded = uploadedSlotIds.has(document.id)
            return (
              <div className="document-item" key={document.id}>
                <div>
                  <strong>{document.label}</strong>
                  <p>{uploaded ? 'A file has been uploaded.' : 'No file is currently recorded for this slot.'}</p>
                </div>
                <span className="small-tag">{uploaded ? 'Uploaded' : 'Missing'}</span>
              </div>
            )
          })}
        </div>

        <div className="form-actions">
          <button
            type="button"
            className="primary-button"
            onClick={handleRunPresubmit}
            disabled={presubmitLoading || submittingApplication || alreadySubmitted}
          >
            {presubmitLoading ? 'Checking...' : 'Check application readiness'}
          </button>
        </div>

        {presubmitResult && (
          <div className="form-section-title">Pre-submission validation</div>
        )}

        {presubmitResult && (
          <div className="document-list" aria-live="polite">
            <div className="document-item">
              <div>
                <strong>
                  {!presubmitResult.ready
                    ? 'Application needs attention'
                    : presubmitResult.review_required
                      ? 'Ready to submit — human review required'
                      : 'Application is ready'}
                </strong>
                <p>
                  {!presubmitResult.ready
                    ? 'Resolve the blocking requirements below, then run the readiness check again.'
                    : presubmitResult.review_required
                      ? 'No blocking corrections were found. You may submit, but one or more checks require reviewer assessment.'
                      : 'No blocking requirements were found. You can proceed to the declaration.'}
                </p>
              </div>
              <span className="small-tag">
                {!presubmitResult.ready
                  ? 'Not ready'
                  : presubmitResult.review_required
                    ? 'Review required'
                    : 'Ready'}
              </span>
            </div>

            {blockers.map((blocker, index) => (
              <div className="alert-item" key={`blocker-${index}`}>
                <span>!</span>
                <div>
                  <strong>Blocking requirement</strong>
                  <p>{typeof blocker === 'string' ? blocker : blocker.message}</p>
                  {typeof blocker === 'object' && blocker.action && (
                    <p>{blocker.action}</p>
                  )}
                </div>
              </div>
            ))}

            {reviewItems.map((item, index) => (
              <div className="alert-item" key={`review-${item.finding_id || index}`}>
                <span>i</span>
                <div>
                  <strong>Human review required</strong>
                  <p>{item.message}</p>
                  {item.action && <p>{item.action}</p>}
                </div>
              </div>
            ))}

            {warnings.map((warning, index) => (
              <div className="alert-item" key={`warning-${index}`}>
                <span>i</span>
                <div>
                  <strong>Warning</strong>
                  <p>{warning}</p>
                </div>
              </div>
            ))}

            {blockers.length === 0 &&
              warnings.length === 0 &&
              reviewItems.length === 0 && (
                <p className="stat-note">No blockers, warnings or review items were returned by the backend.</p>
              )}
          </div>
        )}

        {submissionError && (
          <div className="alert-item" role="alert">
            <span>!</span>
            <div>
              <strong>Unable to proceed</strong>
              <p>{submissionError}</p>
            </div>
          </div>
        )}

        {submissionResult && (
          <div className="document-item" role="status">
            <div>
              <strong>Application submitted successfully</strong>
              <p>Reference: {submissionResult.application_ref}</p>
              <p>New version: {submissionResult.version}</p>
              <p>State: {submissionResult.state}</p>
              <p>{submissionResult.message}</p>
            </div>
            <span className="small-tag">Submitted</span>
          </div>
        )}

        {presubmitResult?.ready && !alreadySubmitted && !submissionResult && (
          <form onSubmit={handleFinalSubmit}>
            <div className="form-section-title">Vendor declaration</div>
            <p className="stat-note">
              By accepting this declaration, you confirm that the information and documents submitted in this application are complete and accurate to the best of your knowledge, and that you are authorised to submit this application on behalf of the vendor.
            </p>

            <label className="form-field full-field" style={{ display: 'flex', alignItems: 'flex-start', gap: '10px' }}>
              <input
                type="checkbox"
                checked={declarationAccepted}
                onChange={(event) => setDeclarationAccepted(event.target.checked)}
                disabled={submittingApplication}
                style={{ width: 'auto', marginTop: '3px' }}
              />
              <span>I have read and accept the vendor declaration. *</span>
            </label>

            <div className="form-actions">
              <button
                type="submit"
                className="primary-button save-button"
                disabled={!declarationAccepted || submittingApplication}
              >
                {submittingApplication ? 'Submitting...' : 'Submit Application'}
              </button>
            </div>
          </form>
        )}

        {alreadySubmitted && (
          <p className="stat-note">
            This application has already left the editable draft stage. Check Application Status for the latest evaluation result.
          </p>
        )}
      </section>
    )
  }

  function renderDashboard() {
    return (
      <>
        <section className="welcome-section">
          <div>
            <p className="eyebrow">VENDOR WORKSPACE</p>
            <h2>Welcome back!</h2>
            <p>
              Track your onboarding progress and manage your application.
            </p>
          </div>
          <div className="welcome-icon">✦</div>
        </section>

        <section className="stats-grid">
          <div className="stat-card">
            <span className="stat-label">APPLICATION STATUS</span>
            <h2 className="status-text">Action Required</h2>
            <span className="stat-note">Some updates are needed</span>
          </div>

          <div className="stat-card">
            <span className="stat-label">APPLICATION REFERENCE</span>
            <h2>{localStorage.getItem('vf_application_ref') || 'Vendor Application'}</h2>
            <span className="stat-note">Your application ID</span>
          </div>

          <div className="stat-card">
            <span className="stat-label">COMPLETION</span>
            <h2>75%</h2>
            <div className="progress-track">
              <div className="progress-fill"></div>
            </div>
          </div>
        </section>

        <section className="content-grid">
          <div className="panel">
            <div className="panel-heading">
              <div>
                <h3>Onboarding progress</h3>
                <p>Follow the steps to complete your registration.</p>
              </div>
              <span className="small-tag">In progress</span>
            </div>

            {[
              [
                '✓',
                'Company information',
                'Basic business details submitted',
                'Completed',
              ],
              [
                '✓',
                'Documents submitted',
                'Initial documents uploaded',
                'Completed',
              ],
              [
                '3',
                'Review and corrections',
                'Some information needs your attention',
                'Current',
              ],
              [
                '4',
                'Final decision',
                'Awaiting review completion',
                'Pending',
              ],
            ].map((step, index) => (
              <div
                className={`progress-step ${
                  index < 2
                    ? 'completed'
                    : index === 2
                      ? 'current'
                      : ''
                }`}
                key={step[1]}
              >
                <span className="step-number">{step[0]}</span>
                <div>
                  <strong>{step[1]}</strong>
                  <p>{step[2]}</p>
                </div>
                <span
                  className={`step-status ${index === 3 ? 'pending' : ''}`}
                >
                  {step[3]}
                </span>
              </div>
            ))}
          </div>

          <div className="panel action-panel">
            <div className="panel-heading">
              <div>
                <h3>Attention needed</h3>
                <p>Items requiring an update</p>
              </div>
              <span className="alert-count">9</span>
            </div>

            {[
              ['Tax information', 'Check your PAN and CIN details.'],
              ['Document quality', 'Some documents need clearer scans.'],
              ['Bank information', 'Verify your bank account details.'],
            ].map((item) => (
              <div className="alert-item" key={item[0]}>
                <span>!</span>
                <div>
                  <strong>{item[0]}</strong>
                  <p>{item[1]}</p>
                </div>
              </div>
            ))}

            <button
              className="primary-button"
              onClick={() => setActivePage('Action Required')}
            >
              Review requirements →
            </button>
          </div>
        </section>
      </>
    )
  }

  function renderCompanyProfile() {
    return (
      <section className="panel profile-panel">
        <div className="panel-heading">
          <div>
            <h3>Company information</h3>
            <p>
              Enter your business details as registered with the relevant
              authorities.
            </p>
          </div>
          <span className="small-tag">Profile</span>
        </div>

        <form onSubmit={handleSave}>
          <div className="form-section-title">Business details</div>

          <div className="form-grid">
            <label className="form-field">
              Company / Legal business name *
              <input
                name="company_name"
                value={profile.company_name}
                onChange={handleChange}
                placeholder="Enter registered company name"
                required
              />
            </label>

            <label className="form-field">
              Business type *
              <select
                name="business_type"
                value={profile.business_type}
                onChange={handleChange}
                required
              >
                <option value="">Select business type</option>
                <option value="Private Limited">Private Limited</option>
                <option value="Public Limited">Public Limited</option>
                <option value="LLP">Limited Liability Partnership (LLP)</option>
                <option value="Partnership">Partnership</option>
                <option value="Proprietorship">Sole Proprietorship</option>
                <option value="Other">Other</option>
              </select>
            </label>

            <label className="form-field">
              Business email *
              <input
                type="email"
                name="email"
                value={profile.email}
                onChange={handleChange}
                placeholder="company@example.com"
                required
              />
            </label>

            <label className="form-field">
              Contact phone *
              <input
                type="tel"
                name="phone"
                value={profile.phone}
                onChange={handleChange}
                placeholder="Enter contact number"
                required
              />
            </label>
          </div>

          <div
            className="form-section-title"
            id="authorised-representative-section"
          >
            Authorised Representative Details
          </div>

          <p className="stat-note">
            Provide the details of the person authorised to represent your
            company.
          </p>

          <div className="form-grid">
            <label className="form-field">
              Authorised Representative Name *
              <input
                id="authorised-rep-name"
                name="authorised_rep_name"
                value={profile.authorised_rep_name || ''}
                onChange={handleChange}
                placeholder="Enter representative's full name"
                required
              />
            </label>

            <label className="form-field">
              Designation *
              <input
                name="authorised_rep_designation"
                value={profile.authorised_rep_designation || ''}
                onChange={handleChange}
                placeholder="e.g. Director, CEO, Partner"
                required
              />
            </label>
          </div>

          <div className="form-section-title">
            Registered business address
          </div>

          <div className="form-grid">
            <label className="form-field full-field">
              Address line *
              <input
                name="address_line1"
                value={profile.address_line1}
                onChange={handleChange}
                placeholder="Building, street and area"
                required
              />
            </label>

            <label className="form-field">
              City *
              <input
                name="city"
                value={profile.city}
                onChange={handleChange}
                placeholder="Enter city"
                required
              />
            </label>

            <label className="form-field">
              State *
              <input
                name="state"
                value={profile.state}
                onChange={handleChange}
                placeholder="Enter state"
                required
              />
            </label>

            <label className="form-field">
              PIN code *
              <input
                name="postal_code"
                value={profile.postal_code}
                onChange={handleChange}
                placeholder="6-digit PIN code"
                required
              />
            </label>

            <label className="form-field">
              Country *
              <input
                name="country"
                value={profile.country}
                onChange={handleChange}
                required
              />
            </label>
          </div>

          <div className="form-actions">
            {saved && (
              <span className="save-message">
                Details saved in this browser session.
              </span>
            )}
            <button type="submit" className="primary-button save-button">
              Save Draft
            </button>
          </div>
        </form>
      </section>
    )
  }

  async function handleRefreshStatus() {
    setStatusRefreshing(true)

    try {
      await loadApplication()
    } catch (error) {
      console.error('Status refresh error:', error)
      alert('Could not refresh application status: ' + error.message)
    } finally {
      setStatusRefreshing(false)
    }
  }

  const loadRequiredActions = useCallback(async () => {
    setActionLoading(true)
    setActionError('')

    try {
      const response = await fetch(`${API}/status`)
      const result = await response.json()

      if (!response.ok) {
        throw new Error(result.detail || 'Unable to load required actions')
      }

      const preSubmitResponse = await fetch(`${API}/presubmit`, {
        method: 'POST',
      })

      const preSubmitResult = await preSubmitResponse.json()

      if (!preSubmitResponse.ok) {
        throw new Error(
          preSubmitResult.detail || 'Unable to check draft requirements'
        )
      }

      setActionData({
        ...result,
        presubmit: preSubmitResult,
      })
    } catch (error) {
      console.error('Required actions loading error:', error)
      setActionError(error.message)
    } finally {
      setActionLoading(false)
    }
  }, [])

  useEffect(() => {
    if (activePage === 'Action Required') {
      loadRequiredActions()
    }
  }, [activePage, loadRequiredActions])

  function handleActionClick(action) {
    const actionDestinations = {
      A1: {
        page: 'Company Profile',
        profileField: 'authorised-rep-name',
      },
      A2: {
        page: 'Documents',
        documentSlot: 'pan_card',
      },
      A3: {
        page: 'Documents',
        documentSlot: 'incorporation_cert',
      },
      A4: {
        page: 'Documents',
        documentSlot: 'bank_evidence:acct-demo-1',
      },
      A5: {
        page: 'Tax Registrations',
        taxField: 'tax-pan-input',
      },
      A6: {
        page: 'Tax Registrations',
        taxField: 'tax-cin-input',
      },
      A7: {
        page: 'Bank Accounts',
        bankField: 'bank-ifsc-input',
      },
      A8: {
        page: 'Bank Accounts',
        bankField: 'bank-account-number-input',
      },
      R1: {
        page: 'Tax Registrations',
        taxField: 'gstin-status-select',
      },
    }

    const destination = actionDestinations[action?.ref]

    if (!destination) return

    setPendingDocumentSlot(destination.documentSlot || '')
    setPendingProfileField(destination.profileField || '')
    setPendingTaxField(destination.taxField || '')
    setPendingBankField(destination.bankField || '')
    setActivePage(destination.page)
  }

  // Scroll to the selected document after the Documents page renders.
  useEffect(() => {
    if (activePage !== 'Documents' || !pendingDocumentSlot) {
      return
    }

    const targetElement = document.getElementById(
      `document-slot-${pendingDocumentSlot}`
    )

    if (targetElement) {
      targetElement.scrollIntoView({
        behavior: 'smooth',
        block: 'center',
      })
    }

    setPendingDocumentSlot('')
  }, [activePage, pendingDocumentSlot])

  // Scroll to the authorised representative field after Company Profile renders.
  useEffect(() => {
    if (activePage !== 'Company Profile' || !pendingProfileField) {
      return
    }

    const targetElement = document.getElementById(pendingProfileField)

    if (targetElement) {
      targetElement.scrollIntoView({
        behavior: 'smooth',
        block: 'center',
      })

      targetElement.focus({ preventScroll: true })
    }

    setPendingProfileField('')
  }, [activePage, pendingProfileField])

  // Scroll to the selected tax field after the Tax Registrations page renders.
  useEffect(() => {
    if (activePage !== 'Tax Registrations' || !pendingTaxField) {
      return
    }

    const targetElement = document.getElementById(pendingTaxField)

    if (targetElement) {
      targetElement.scrollIntoView({
        behavior: 'smooth',
        block: 'center',
      })

      targetElement.focus({ preventScroll: true })
    }

    setPendingTaxField('')
  }, [activePage, pendingTaxField])

  // Scroll to the requested bank correction field after the page renders.
  useEffect(() => {
    if (activePage !== 'Bank Accounts' || !pendingBankField) {
      return
    }

    const targetElement = document.getElementById(pendingBankField)

    if (targetElement) {
      targetElement.scrollIntoView({
        behavior: 'smooth',
        block: 'center',
      })
      targetElement.focus({ preventScroll: true })
    }

    setPendingBankField('')
  }, [activePage, pendingBankField])

  function renderActionRequired() {
    const actions = actionData?.required_actions?.length
      ? actionData.required_actions
      : actionData?.presubmit?.blockers || []

    const documentStatuses = actionData?.document_statuses || {}

    function actionTitle(action, index) {
      if (typeof action === 'string') return action

      if (!action || typeof action !== 'object') {
        return `Required action ${index + 1}`
      }

      return (
        action.text ||
        action.title ||
        action.label ||
        action.action ||
        action.code ||
        `Required action ${index + 1}`
      )
    }

    function actionDescription(action) {
      if (
        !action ||
        typeof action !== 'object' ||
        typeof action === 'string'
      ) {
        return ''
      }

      return (
        action.description ||
        action.message ||
        action.instruction ||
        action.reason ||
        ''
      )
    }

    return (
      <section className="panel profile-panel">
        <div className="panel-heading">
          <div>
            <h3>Items requiring your attention</h3>
            <p>
              These actions are provided by the application review system.
            </p>
          </div>

          <button
            type="button"
            className="primary-button"
            onClick={loadRequiredActions}
            disabled={actionLoading}
          >
            {actionLoading ? 'Refreshing...' : 'Refresh actions'}
          </button>
        </div>

        {actionLoading && !actionData && (
          <p>Loading required actions...</p>
        )}

        {actionError && (
          <p role="alert">
            Could not load required actions: {actionError}
          </p>
        )}

        {actionData && (
          <>
            <div className="form-section-title">Required actions</div>

            {actionData.presubmit?.warnings?.length > 0 && (
              <div className="alert-item">
                <span>i</span>
                <div>
                  <strong>Additional information</strong>
                  <p>{actionData.presubmit.warnings.join(' · ')}</p>
                </div>
              </div>
            )}

            {actions.length > 0 ? (
              <div className="document-list">
                {actions.map((action, index) => {
                  const isClickable = [
                    'A1',
                    'A2',
                    'A3',
                    'A4',
                    'A5',
                    'A6',
                    'A7',
                    'A8',
                    'R1',
                  ].includes(action?.ref)

                  return (
                    <div
                      className={`alert-item ${
                        isClickable ? 'action-clickable' : ''
                      }`}
                      key={action.ref || index}
                      role={isClickable ? 'button' : undefined}
                      tabIndex={isClickable ? 0 : undefined}
                      onClick={() => handleActionClick(action)}
                      onKeyDown={(event) => {
                        if (
                          isClickable &&
                          (event.key === 'Enter' || event.key === ' ')
                        ) {
                          event.preventDefault()
                          handleActionClick(action)
                        }
                      }}
                      title={
                        isClickable
                          ? 'Click to resolve this action'
                          : undefined
                      }
                    >
                      <span>!</span>

                      <div>
                        <strong>{actionTitle(action, index)}</strong>

                        {action.ref && (
                          <p className="stat-note">
                            Reference: {action.ref} · Type:{' '}
                            {action.kind || 'action'}
                          </p>
                        )}

                        {actionDescription(action) && (
                          <p>{actionDescription(action)}</p>
                        )}

                        {isClickable && (
                          <p className="stat-note action-hint">
                            Click to resolve →
                          </p>
                        )}
                      </div>
                    </div>
                  )
                })}
              </div>
            ) : (
              <p>
                No specific correction actions are currently listed by the
                review system.
              </p>
            )}

            <div className="form-section-title">
              Document review status
            </div>

            {Object.keys(documentStatuses).length > 0 ? (
              <div className="document-list">
                {Object.entries(documentStatuses).map(([slot, status]) => (
                  <div className="document-item" key={slot}>
                    <div>
                      <strong>{slot.replaceAll('_', ' ')}</strong>
                    </div>
                    <span className="small-tag">
                      {typeof status === 'string'
                        ? status
                        : status?.status || 'See details'}
                    </span>
                  </div>
                ))}
              </div>
            ) : (
              <p>No document review statuses are available yet.</p>
            )}

            <p className="stat-note">
              Application reference: {actionData.application_ref} · Version:{' '}
              {actionData.version}
            </p>
          </>
        )}
      </section>
    )
  }

  function renderApplicationStatus() {
    const stateLabels = {
      DRAFT: 'Draft',
      ACTION_REQUIRED: 'Action Required',
      PROCESSING: 'Under Review',
      APPROVED: 'Approved',
      REJECTED: 'Rejected',
    }

    const applicationState = applicationDetails?.state
    const decisionStatus = applicationDetails?.decision_status

    return (
      <section className="panel profile-panel">
        <div className="panel-heading">
          <div>
            <h3>Application overview</h3>
            <p>
              View the latest status returned by the onboarding system.
            </p>
          </div>

          <button
            type="button"
            className="primary-button"
            onClick={handleRefreshStatus}
            disabled={statusRefreshing}
          >
            {statusRefreshing ? 'Refreshing...' : 'Refresh status'}
          </button>
        </div>

        {!applicationDetails ? (
          <p>Loading application details...</p>
        ) : (
          <>
            <div className="stats-grid">
              <div className="stat-card">
                <span className="stat-label">APPLICATION STATE</span>
                <h2 className="status-text">
                  {stateLabels[applicationState] ||
                    applicationState ||
                    'Unknown'}
                </h2>
                <span className="stat-note">Current workflow stage</span>
              </div>

              <div className="stat-card">
                <span className="stat-label">REVIEW STATUS</span>
                <h2>
                  {decisionStatus
                    ? decisionStatus.replaceAll('_', ' ')
                    : 'Not yet decided'}
                </h2>
                <span className="stat-note">Latest decision status</span>
              </div>

              <div className="stat-card">
                <span className="stat-label">APPLICATION VERSION</span>
                <h2>{applicationDetails.version ?? '—'}</h2>
                <span className="stat-note">Current saved version</span>
              </div>
            </div>

            <div className="form-section-title">
              Application reference
            </div>

            <div className="document-item">
              <div>
                <strong>{applicationDetails.application_ref}</strong>
                <p>Keep this reference for future communication.</p>
              </div>
              <span className="small-tag">Application ID</span>
            </div>

            <p className="stat-note">
              This information is loaded directly from the backend. Refresh
              the status to check for the latest update.
            </p>
          </>
        )}
      </section>
    )
  }

  function handleApplyExtractedDetails(slotId) {
    const values = extractionDrafts[slotId] || {}
    const legalName = (values.legal_name || '').trim()
    const pan = (values.pan || '').trim().toUpperCase()
    const gstin = (values.gstin || '').trim().toUpperCase()
    const cin = (values.cin || '').trim().toUpperCase()
    const accountHolderName = (values.account_holder_name || '').trim()
    const ifsc = (values.ifsc || '').trim().toUpperCase()

    if (!legalName && !pan && !gstin && !cin && !accountHolderName && !ifsc) {
      alert('There are no supported fields to apply. Please review the extraction result or upload a clearer document.')
      return
    }

    if (legalName) {
      setProfile((previous) => ({ ...previous, company_name: legalName }))
    }
    setTaxDraft((previous) => ({
      ...previous,
      ...(pan ? { pan } : {}),
      ...(gstin ? { gstin, gstinStatus: 'registered', gstinReason: '' } : {}),
      ...(cin ? { cin } : {}),
    }))
    if (accountHolderName || ifsc) {
      setBankDraft((previous) => ({
        ...previous,
        ...(accountHolderName ? { holderName: accountHolderName } : {}),
        ...(ifsc ? { ifsc } : {}),
      }))
    }
    setSaved(false)
    setExtractionAppliedMessage('Extracted candidates copied into the relevant form drafts. Review them and save each section manually.')
    setActivePage(legalName ? 'Company Profile' : (accountHolderName || ifsc ? 'Bank Accounts' : 'Tax Registrations'))
  }

  function getExtractionSignal(field, value) {
    const text = String(value || '').trim().toUpperCase()
    const patterns = {
      pan: /^[A-Z]{5}[0-9]{4}[A-Z]$/,
      gstin: /^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$/,
      cin: /^[A-Z]{1,3}[0-9]{2,6}[A-Z]{2,4}[0-9]{3,8}$/,
      ifsc: /^[A-Z]{4}0[A-Z0-9]{6}$/,
    }
    if (patterns[field]) {
      return patterns[field].test(text)
        ? { label: 'Format matched', tone: 'good', detail: 'Format pattern matched; identity and ownership are not verified.' }
        : { label: 'Format needs review', tone: 'warning', detail: 'The value does not match the expected format.' }
    }
    return { label: 'Name candidate', tone: 'review', detail: 'Found near a name label. Confirm spelling against the original document.' }
  }

  function updateExtractionDraft(slotId, field, value) {
    setExtractionDrafts((previous) => ({
      ...previous,
      [slotId]: { ...(previous[slotId] || {}), [field]: value },
    }))
  }

  function renderDocuments() {
    const requiredDocuments = [
      {
        id: 'pan_card',
        title: 'PAN Card',
        description: 'Company PAN card',
      },
      {
        id: 'incorporation_cert',
        title: 'Incorporation Certificate',
        description: 'Certificate of company incorporation',
      },
      {
        id: 'bank_evidence:acct-demo-1',
        title: 'Bank Evidence',
        description: 'Bank statement or cancelled cheque',
      },
      {
        id: 'gst_cert',
        title: 'GST Registration Certificate',
        description:
          'GST registration certificate for vendors registered under GST',
      },
      ...(authLetterSlotId
        ? [{
            id: authLetterSlotId,
            title: 'Bank Account Holder Authorisation Letter',
            description:
              'Optional supporting authorisation evidence if the account holder differs from the legal business entity.',
          }]
        : []),
    ]

    return (
      <section className="panel profile-panel">
        <div className="panel-heading">
          <div>
            <h3>Company documents</h3>
            <p>
              Manage the documents required for vendor verification.
            </p>
          </div>
          <span className="small-tag">Documents</span>
        </div>

        <div className="form-section-title">Required documents</div>
        {extractionAppliedMessage && (
          <div className="alert-item" role="status">
            <span>i</span>
            <div>
              <strong>Details copied to form drafts</strong>
              <p>{extractionAppliedMessage}</p>
            </div>
          </div>
        )}

        <div className="document-list">
          {requiredDocuments.map((document) => {
            const uploadedDocument = documents.find(
              (item) => item.slot_id === document.id
            )

            return (
              <div
                className="document-item"
                key={document.id}
                id={`document-slot-${document.id}`}
              >
                <div>
                  <strong>{document.title}</strong>
                  <p>{document.description}</p>

                  {uploadedDocument && (
                    <>
                      <p className="document-filename">
                        File: {uploadedDocument.filename}
                      </p>
                      <p className="document-filename">
                        Text extraction: {uploadedDocument.extraction_status || 'Pending'}
                        {uploadedDocument.extraction_method ? ` · ${uploadedDocument.extraction_method}` : ''}
                      </p>
                      {uploadedDocument.extracted_fields && Object.keys(uploadedDocument.extracted_fields).length > 0 && (
                        <div className="extraction-review-panel">
                          <strong>Review extracted details</strong>
                          <p className="stat-note">Check every value against the original document. You can edit candidates before copying them into your form drafts.</p>
                          {['legal_name', 'pan', 'gstin', 'cin', 'account_holder_name', 'ifsc'].filter((field) => uploadedDocument.extracted_fields[field] !== undefined).map((field) => {
                            const rawValue = uploadedDocument.extracted_fields[field]
                            const initialValue = Array.isArray(rawValue) ? (rawValue[0] || '') : String(rawValue ?? '')
                            const draftValue = extractionDrafts[document.id]?.[field] ?? initialValue
                            const signal = getExtractionSignal(field, draftValue)
                            return (
                              <label className="form-field extraction-field" key={field}>
                                <span className="extraction-field-heading">
                                  <span>{field.replaceAll('_', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase())}</span>
                                  <span className={`extraction-signal ${signal.tone}`}>{signal.label}</span>
                                </span>
                                <input
                                  value={draftValue}
                                  onChange={(event) => updateExtractionDraft(document.id, field, event.target.value)}
                                  autoComplete="off"
                                />
                                <small className="extraction-signal-detail">{signal.detail}</small>
                              </label>
                            )
                          })}
                          <button type="button" className="primary-button" onClick={() => handleApplyExtractedDetails(document.id)}>
                            Review & use these details
                          </button>
                        </div>
                      )}
                      {uploadedDocument.extraction_warnings?.map((warning, index) => (
                        <p className="document-filename" key={index}>{warning}</p>
                      ))}
                    </>
                  )}
                </div>

                <div className="document-actions">
                  <span className="small-tag">
                    {uploadedDocument ? 'Uploaded' : 'Not uploaded'}
                  </span>

                  <label className="document-upload-button">
                    {uploadingSlot === document.id
                      ? 'Uploading...'
                      : uploadedDocument
                        ? 'Replace file'
                        : 'Choose file'}

                    <input
                      type="file"
                      accept=".pdf,.jpg,.jpeg,.png"
                      disabled={uploadingSlot !== '' || deletingSlot !== ''}
                      onChange={(event) =>
                        handleDocumentUpload(document.id, event)
                      }
                    />
                  </label>

                  {uploadedDocument && (
                    <button
                      type="button"
                      className="document-delete-button"
                      disabled={deletingSlot !== '' || uploadingSlot !== ''}
                      onClick={() =>
                        handleDeleteDocument(document.id, document.title)
                      }
                    >
                      {deletingSlot === document.id ? 'Removing...' : 'Remove'}
                    </button>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      </section>
    )
  }

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-icon">V</div>
          <div>
            <h2>VendorFlow</h2>
            <span>ONBOARDING PORTAL</span>
          </div>
        </div>

        <div className="menu-heading">WORKSPACE</div>

        <nav>
          {menuItems.map((item) => (
            <button
              key={item.label}
              className={`menu-item ${
                activePage === item.label ? 'active' : ''
              }`}
              onClick={() => setActivePage(item.label)}
            >
              <span className="menu-icon">{item.icon}</span>
              {item.label}
            </button>
          ))}
        </nav>

        <div className="sidebar-bottom">
          <div className="help-card">
            <strong>Need help?</strong>
            <p>Contact our vendor support team.</p>
            <button type="button">Get support</button>
          </div>

          <div className="user-profile">
            <div className="avatar">VD</div>
            <div>
              <strong>Vendor Demo</strong>
              <span>Vendor Account</span>
            </div>
          </div>
        </div>
      </aside>

      <main className="main-content">
        <header className="topbar">
          <div>
            <span className="breadcrumb">
              Workspace / {activePage}
            </span>
            <h1>{activePage}</h1>
          </div>

          <div className="topbar-right">
            <span className="notification">♧</span>
            <div className="avatar">VD</div>
          </div>
        </header>

        {activePage === 'Dashboard' && renderDashboard()}
        {activePage === 'Company Profile' && renderCompanyProfile()}
        {activePage === 'Tax Registrations' && renderTaxRegistrations()}
        {activePage === 'Bank Accounts' && renderBankAccounts()}
        {activePage === 'Documents' && renderDocuments()}
        {activePage === 'Validation' && renderValidation()}
        {activePage === 'Application Status' && renderApplicationStatus()}
        {activePage === 'Review & Submit' && renderReviewSubmit()}
        {activePage === 'Action Required' && renderActionRequired()}

        <footer>VendorFlow · Vendor Onboarding Portal</footer>
      </main>
    </div>
  )
}

export default App