const loginPanel = document.getElementById('login-panel');
const loginForm = document.getElementById('login-form');
const loginError = document.getElementById('login-error');
const loginButton = document.getElementById('login-submit');
const forgotPasswordLink = document.getElementById('forgot-password-link');
const forgotPasswordPanel = document.getElementById('forgot-password-panel');
const forgotPasswordForm = document.getElementById('forgot-password-form');
const forgotPasswordSubmit = document.getElementById('forgot-password-submit');
const forgotPasswordMessage = document.getElementById('forgot-password-message');
const forgotPasswordBack = document.getElementById('forgot-password-back');
const passwordChangePanel = document.getElementById('password-change-panel');
const passwordChangeForm = document.getElementById('password-change-form');
const passwordChangeError = document.getElementById('password-change-error');
const passwordChangeButton = document.getElementById('password-change-submit');
const activationPanel = document.getElementById('activation-panel');
const activationForm = document.getElementById('activation-form');
const activationMessage = document.getElementById('activation-message');
const activationSubmit = document.getElementById('activation-submit');
const activationContinue = document.getElementById('activation-continue');
const assistant = document.getElementById('assistant');
const profileName = document.getElementById('profile-name');
const profileDetail = document.getElementById('profile-detail');
const avatar = document.getElementById('avatar');
const logoutButton = document.getElementById('logout');
const departmentSelect = document.getElementById('department');
const queryForm = document.getElementById('query-form');
const questionInput = document.getElementById('question');
const characterCount = document.getElementById('character-count');
const submitButton = document.getElementById('submit');
const answerState = document.getElementById('answer-state');
const answerCard = document.getElementById('answer-card');
const answerElement = document.getElementById('answer');
const answerStatus = document.getElementById('answer-status');
const citationsElement = document.getElementById('citations');
const sourcesEmpty = document.getElementById('sources-empty');
const sourceCount = document.getElementById('source-count');
const adminPanel = document.getElementById('admin-panel');
const createUserForm = document.getElementById('create-user-form');
const adminMessage = document.getElementById('admin-message');
const usersList = document.getElementById('users-list');
const emailSetupWarning = document.getElementById('email-setup-warning');
const bulkUsersForm = document.getElementById('bulk-users-form');
const bulkUsersMessage = document.getElementById('bulk-users-message');
const bulkUsersPreview = document.getElementById('bulk-users-preview');
const bulkPreviewButton = document.getElementById('bulk-preview-submit');
const bulkCreateButton = document.getElementById('bulk-create-valid');
const auditList = document.getElementById('audit-list');
const refreshAuditButton = document.getElementById('refresh-audit');
const sopUploadForm = document.getElementById('sop-upload-form');
const sopUploadButton = document.getElementById('sop-upload-submit');
const sopUploadMessage = document.getElementById('sop-upload-message');
const sopList = document.getElementById('sop-list');
const refreshSopsButton = document.getElementById('refresh-sops');
const librarySearch = document.getElementById('library-search');
const libraryList = document.getElementById('library-list');
const refreshLibraryButton = document.getElementById('refresh-library');
const libraryCategoryFilter = document.getElementById('library-category-filter');
const libraryTagFilter = document.getElementById('library-tag-filter');
const libraryDateAfter = document.getElementById('library-date-after');
const libraryDateBefore = document.getElementById('library-date-before');
const categoryCreateForm = document.getElementById('category-create-form');
const categoryMessage = document.getElementById('category-message');
const categoryList = document.getElementById('category-list');
const sopCategorySelect = document.getElementById('sop-category');
const documentBulkFiles = document.getElementById('document-bulk-files');
const documentBulkDefaultCategory = document.getElementById('document-bulk-default-category');
const documentBulkDefaultDepartment = document.getElementById('document-bulk-default-department');
const documentBulkMetadata = document.getElementById('document-bulk-metadata');
const documentBulkSubmit = document.getElementById('document-bulk-submit');
const documentBulkMessage = document.getElementById('document-bulk-message');
const documentBulkResults = document.getElementById('document-bulk-results');
const documentUploadProgress = document.getElementById('document-upload-progress');
const refreshDocumentCatalogButton = document.getElementById('refresh-document-catalog');
const adminDocumentSearch = document.getElementById('admin-document-search');
const adminDocumentCategory = document.getElementById('admin-document-category');
const adminDocumentStatus = document.getElementById('admin-document-status');
const adminDocumentTag = document.getElementById('admin-document-tag');
const adminDocumentDateAfter = document.getElementById('admin-document-date-after');
const adminDocumentDateBefore = document.getElementById('admin-document-date-before');
const adminShowDeleted = document.getElementById('admin-show-deleted');
const documentCatalogList = document.getElementById('document-catalog-list');
const refreshFailedUploadsButton = document.getElementById('refresh-failed-uploads');
const failedUploadList = document.getElementById('failed-upload-list');
const documentAuditSearch = document.getElementById('document-audit-search');
const searchDocumentAuditButton = document.getElementById('search-document-audit');
const documentAuditList = document.getElementById('document-audit-list');

let accessToken = null;
let currentUser = null;
let approvedSops = [];
let documentCategories = [];
let bulkPreviewUsers = [];
let activationToken = new URLSearchParams(window.location.hash.slice(1)).get('token');
let credentialLinkMode = window.location.pathname === '/reset-password' ? 'reset' : 'activate';

async function apiFetch(url, options = {}) {
  const headers = new Headers(options.headers || {});
  if (accessToken) headers.set('Authorization', `Bearer ${accessToken}`);
  if (options.body && !(options.body instanceof FormData)) {
    headers.set('Content-Type', 'application/json');
  }

  let response;
  try {
    response = await fetch(url, { ...options, headers });
  } catch {
    throw new Error('Could not connect. Check your connection and try again.');
  }

  if (response.status === 401 && accessToken) {
    signOut();
    throw new Error('Your session expired. Please sign in again.');
  }

  let data;
  try {
    data = await response.json();
  } catch {
    throw new Error('The server returned an unexpected response. Please try again.');
  }
  if (!response.ok) {
    const detail = Array.isArray(data.detail)
      ? data.detail.map((item) => item.msg).filter(Boolean).join(' ')
      : data.detail;
    throw new Error(detail || 'The request could not be completed.');
  }
  return data;
}

function signOut() {
  accessToken = null;
  currentUser = null;
  assistant.classList.add('hidden');
  logoutButton.classList.add('hidden');
  passwordChangePanel.classList.add('hidden');
  activationPanel.classList.add('hidden');
  forgotPasswordPanel.classList.add('hidden');
  passwordChangeForm.reset();
  activationForm.reset();
  loginPanel.classList.remove('hidden');
  loginForm.reset();
  loginError.classList.add('hidden');
  document.getElementById('email').focus();
}

function setAnswerStatus(message, state = 'ready') {
  answerStatus.lastChild.textContent = ` ${message}`;
  answerStatus.classList.toggle('is-loading', state === 'loading');
  answerStatus.classList.toggle('is-error', state === 'error');
  answerStatus.classList.toggle('is-warning', state === 'warning');
}

function setAdminMessage(message, isError = false) {
  adminMessage.textContent = message;
  adminMessage.classList.toggle('error', isError);
}

function setSopUploadMessage(message, isError = false) {
  sopUploadMessage.textContent = message;
  sopUploadMessage.classList.toggle('error', isError);
}

async function showSignedIn(user) {
  currentUser = user;
  documentBulkDefaultDepartment.value = user.department === 'All' ? '' : user.department;
  passwordChangePanel.classList.add('hidden');
  activationPanel.classList.add('hidden');
  loginPanel.classList.add('hidden');
  loginForm.reset();
  loginError.classList.add('hidden');
  assistant.classList.remove('hidden');
  logoutButton.classList.remove('hidden');
  profileName.textContent = user.name;
  profileDetail.textContent = `${user.department} · ${user.role}`;
  avatar.textContent = user.name.trim().charAt(0).toUpperCase() || 'F';
  adminPanel.classList.toggle('hidden', user.role !== 'admin');
  departmentSelect.replaceChildren();
  departmentSelect.disabled = true;

  try {
    const { departments } = await apiFetch('/api/departments');
    if (user.role === 'admin') {
      const allOption = document.createElement('option');
      allOption.value = '';
      allOption.textContent = 'All departments';
      departmentSelect.append(allOption);
    }
    departments.forEach((department) => {
      const option = document.createElement('option');
      option.value = department;
      option.textContent = department;
      departmentSelect.append(option);
    });
    if (user.role !== 'admin') departmentSelect.value = user.department;
  } catch (error) {
    setAnswerStatus(error.message, 'error');
  } finally {
    departmentSelect.disabled = false;
  }

  await loadDocumentCategories();
  if (user.role === 'admin') {
    loadAuditLogs();
    loadUsers();
    loadSops();
    loadEmailStatus();
    loadAdminCategories();
    loadDocumentCatalog();
    loadFailedUploads();
    loadDocumentAudit();
  }
  loadApprovedSops();
  questionInput.focus();
}

function showPasswordChange(user) {
  currentUser = null;
  loginPanel.classList.add('hidden');
  assistant.classList.add('hidden');
  passwordChangePanel.classList.remove('hidden');
  logoutButton.classList.remove('hidden');
  passwordChangeForm.reset();
  passwordChangeError.textContent = `Signed in as ${user.email}. Set a new password to continue.`;
  passwordChangeError.classList.remove('error');
  document.getElementById('new-user-password').focus();
}

function showActivationPage() {
  loginPanel.classList.add('hidden');
  forgotPasswordPanel.classList.add('hidden');
  activationPanel.classList.remove('hidden');
  const isReset = credentialLinkMode === 'reset';
  document.getElementById('credential-eyebrow').textContent =
    isReset ? 'ACCOUNT RECOVERY' : 'ACCOUNT ACTIVATION';
  document.getElementById('credential-title').textContent =
    isReset ? 'Choose a new password' : 'Activate your account';
  document.getElementById('credential-description').textContent = isReset
    ? 'Choose a new password to regain access to your account.'
    : 'Choose a password to finish activating your account.';
  activationSubmit.firstChild.textContent = isReset ? 'Reset password ' : 'Activate account ';
  if (!activationToken) {
    activationMessage.textContent = isReset
      ? 'This password reset link is invalid or incomplete. Request a new reset link from the sign-in page.'
      : 'This activation link is invalid or incomplete. Ask an administrator to resend the invitation.';
    activationMessage.classList.add('error');
    activationSubmit.disabled = true;
    activationContinue.textContent = 'Back to sign in';
    activationContinue.classList.remove('hidden');
    return;
  }
  activationMessage.textContent = isReset
    ? 'This secure reset link can be used once and expires after 30 minutes.'
    : 'This secure activation link can be used once and expires after 24 hours.';
  history.replaceState(null, '', window.location.pathname);
  document.getElementById('activation-new-password').focus();
}

function showAnswerError(error) {
  answerState.classList.add('hidden');
  answerCard.classList.remove('hidden');
  answerElement.textContent = error.message;
  answerElement.classList.add('error');
  setAnswerStatus('Something went wrong', 'error');
}

forgotPasswordLink.addEventListener('click', () => {
  loginPanel.classList.add('hidden');
  forgotPasswordPanel.classList.remove('hidden');
  forgotPasswordMessage.textContent = '';
  forgotPasswordMessage.classList.remove('error');
  document.getElementById('forgot-password-email').value =
    document.getElementById('email').value;
  document.getElementById('forgot-password-email').focus();
});

forgotPasswordBack.addEventListener('click', () => {
  forgotPasswordPanel.classList.add('hidden');
  loginPanel.classList.remove('hidden');
  document.getElementById('email').focus();
});

forgotPasswordForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  forgotPasswordSubmit.disabled = true;
  forgotPasswordMessage.textContent = '';
  forgotPasswordMessage.classList.remove('error');
  try {
    const result = await apiFetch('/api/auth/password-reset', {
      method: 'POST',
      body: JSON.stringify({
        email: document.getElementById('forgot-password-email').value,
      }),
    });
    forgotPasswordMessage.textContent = result.message;
  } catch (error) {
    forgotPasswordMessage.textContent = error.message;
    forgotPasswordMessage.classList.add('error');
  } finally {
    forgotPasswordSubmit.disabled = false;
  }
});

loginForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  loginButton.disabled = true;
  loginError.classList.add('hidden');
  try {
    const result = await apiFetch('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify({
        email: document.getElementById('email').value,
        password: document.getElementById('password').value,
      }),
    });
    accessToken = result.access_token;
    if (result.user.must_change_password) {
      showPasswordChange(result.user);
    } else {
      await showSignedIn(result.user);
    }
  } catch (error) {
    loginError.textContent = error.message;
    loginError.classList.remove('hidden');
  } finally {
    loginButton.disabled = false;
  }
});

passwordChangeForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  passwordChangeButton.disabled = true;
  passwordChangeError.textContent = '';
  passwordChangeError.classList.remove('error');
  const newPassword = document.getElementById('new-user-password').value;
  const confirmPassword = document.getElementById('confirm-user-password').value;
  if (newPassword !== confirmPassword) {
    passwordChangeError.textContent = 'The new passwords do not match.';
    passwordChangeError.classList.add('error');
    passwordChangeButton.disabled = false;
    return;
  }
  try {
    const result = await apiFetch('/api/auth/change-password', {
      method: 'POST',
      body: JSON.stringify({
        new_password: newPassword,
        confirm_password: confirmPassword,
      }),
    });
    accessToken = result.access_token;
    await showSignedIn(result.user);
  } catch (error) {
    passwordChangeError.textContent = error.message;
    passwordChangeError.classList.add('error');
  } finally {
    passwordChangeButton.disabled = false;
  }
});

activationForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  activationSubmit.disabled = true;
  activationMessage.textContent = '';
  activationMessage.classList.remove('error');
  const newPassword = document.getElementById('activation-new-password').value;
  const confirmPassword = document.getElementById('activation-confirm-password').value;
  if (newPassword !== confirmPassword) {
    activationMessage.textContent = 'The new passwords do not match.';
    activationMessage.classList.add('error');
    activationSubmit.disabled = false;
    return;
  }
  try {
    const isReset = credentialLinkMode === 'reset';
    const result = await apiFetch(
      isReset ? '/api/auth/password-reset/confirm' : '/api/auth/activate',
      {
      method: 'POST',
      body: JSON.stringify({
        token: activationToken,
        new_password: newPassword,
        confirm_password: confirmPassword,
      }),
      },
    );
    activationToken = null;
    activationForm.reset();
    activationSubmit.classList.add('hidden');
    activationMessage.textContent = isReset
      ? `Password reset for ${result.email}. You can now sign in with your new password.`
      : `Account activated for ${result.email}. You can now sign in with your new password.`;
    activationContinue.textContent = 'Continue to sign in';
    activationContinue.classList.remove('hidden');
  } catch (error) {
    activationMessage.textContent = error.message;
    activationMessage.classList.add('error');
    activationContinue.textContent = 'Back to sign in';
    activationContinue.classList.remove('hidden');
  } finally {
    activationSubmit.disabled = false;
  }
});

activationContinue.addEventListener('click', () => {
  history.replaceState(null, '', '/');
  activationPanel.classList.add('hidden');
  loginPanel.classList.remove('hidden');
  document.getElementById('email').value = '';
  document.getElementById('password').value = '';
  document.getElementById('email').focus();
});

logoutButton.addEventListener('click', signOut);

async function askSop(event) {
  event.preventDefault();
  const question = questionInput.value.trim();
  if (!question) {
    questionInput.focus();
    questionInput.setCustomValidity('Enter a question to search the SOP library.');
    questionInput.reportValidity();
    return;
  }
  questionInput.setCustomValidity('');

  submitButton.disabled = true;
  queryForm.setAttribute('aria-busy', 'true');
  answerCard.classList.add('hidden');
  answerElement.classList.remove('error');
  answerState.classList.remove('hidden');
  answerState.classList.add('is-searching');
  answerState.querySelector('h2').textContent = 'Looking through approved SOPs…';
  answerState.querySelector('p').textContent = 'Finding the most relevant guidance for your question.';
  setAnswerStatus('Searching approved SOPs', 'loading');
  citationsElement.replaceChildren();
  sourcesEmpty.textContent = 'Searching the approved library…';
  citationsElement.append(sourcesEmpty);
  sourceCount.textContent = '';

  try {
    const result = await apiFetch('/api/query', {
      method: 'POST',
      body: JSON.stringify({
        question,
        department: departmentSelect.value || null,
      }),
    });
    answerState.classList.add('hidden');
    answerState.classList.remove('is-searching');
    answerCard.classList.remove('hidden');
    answerElement.textContent = result.answer || 'No answer was returned.';
    answerElement.classList.remove('error');
    setAnswerStatus(
      result.missing_sop ? 'No approved match found' : 'Grounded in approved SOPs',
      result.missing_sop ? 'warning' : 'ready',
    );
    renderCitations(result.citations || []);
  } catch (error) {
    answerState.classList.remove('is-searching');
    showAnswerError(error);
    citationsElement.replaceChildren();
    sourcesEmpty.textContent = 'Sources are unavailable until the request succeeds.';
    citationsElement.append(sourcesEmpty);
  } finally {
    submitButton.disabled = false;
    queryForm.removeAttribute('aria-busy');
  }
}

function renderCitations(citations) {
  citationsElement.replaceChildren();
  sourceCount.textContent = citations.length ? `(${citations.length})` : '';
  if (!citations.length) {
    sourcesEmpty.textContent = 'No approved SOP citations matched this question.';
    citationsElement.append(sourcesEmpty);
    return;
  }

  citations.forEach((citation) => {
    const card = document.createElement('article');
    card.className = 'citation-card';
    const icon = document.createElement('span');
    icon.className = 'source-icon';
    icon.setAttribute('aria-hidden', 'true');
    icon.textContent = '▤';
    const content = document.createElement('div');
    const title = document.createElement('strong');
    title.className = 'citation-title';
    title.textContent = `${citation.sop_id} — ${citation.title}`;
    const metadata = document.createElement('div');
    metadata.className = 'citation-meta';
    [
      citation.department,
      citation.section,
      `Version ${citation.version}`,
      `Effective ${citation.effective_date}`,
    ].forEach((value) => {
      if (!value) return;
      const item = document.createElement('span');
      item.textContent = value;
      metadata.append(item);
    });
    const source = document.createElement('p');
    source.className = 'citation-source';
    source.textContent = `Source: ${citation.source}`;
    content.append(title, metadata, source);
    card.append(icon, content);
    citationsElement.append(card);
  });
}

queryForm.addEventListener('submit', askSop);
questionInput.addEventListener('keydown', (event) => {
  if (event.key !== 'Enter' || event.shiftKey || event.isComposing) return;
  event.preventDefault();
  queryForm.requestSubmit();
});
questionInput.addEventListener('input', () => {
  characterCount.textContent = `${questionInput.value.length} / 2000`;
  questionInput.setCustomValidity('');
});
document.querySelectorAll('.suggestion').forEach((button) => {
  button.addEventListener('click', () => {
    questionInput.value = button.dataset.question || '';
    characterCount.textContent = `${questionInput.value.length} / 2000`;
    questionInput.focus();
  });
});

createUserForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  const submit = createUserForm.querySelector('button[type="submit"]');
  submit.disabled = true;
  setAdminMessage('');
  try {
    const result = await apiFetch('/api/admin/users', {
      method: 'POST',
      body: JSON.stringify({
        name: document.getElementById('new-name').value,
        email: document.getElementById('new-email').value,
        department: document.getElementById('new-department').value,
        role: document.getElementById('new-role').value,
      }),
    });
    setAdminMessage(`Account created for ${result.email}; activation email sent.`);
    createUserForm.reset();
    await loadUsers();
  } catch (error) {
    setAdminMessage(error.message, true);
    await loadUsers();
  } finally {
    submit.disabled = false;
  }
});

async function loadEmailStatus() {
  try {
    const { configured } = await apiFetch('/api/admin/email-status');
    emailSetupWarning.classList.toggle('hidden', configured);
    emailSetupWarning.textContent = configured
      ? ''
      : 'Email delivery is not configured. Set the SMTP environment variables before creating or inviting accounts.';
    emailSetupWarning.classList.toggle('error', !configured);
  } catch (error) {
    emailSetupWarning.textContent = error.message;
    emailSetupWarning.classList.remove('hidden');
    emailSetupWarning.classList.add('error');
  }
}

bulkUsersForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  const file = document.getElementById('bulk-users-file').files[0];
  if (!file) return;
  bulkPreviewButton.disabled = true;
  bulkUsersMessage.textContent = 'Reading and validating spreadsheet…';
  bulkUsersMessage.classList.remove('error');
  bulkUsersPreview.classList.add('hidden');
  bulkCreateButton.classList.add('hidden');
  bulkPreviewUsers = [];
  try {
    const formData = new FormData();
    formData.append('file', file);
    const result = await apiFetch('/api/admin/users/preview', {
      method: 'POST',
      body: formData,
    });
    bulkPreviewUsers = result.users;
    renderBulkUsersPreview(result.users);
    bulkUsersMessage.textContent = `${result.valid_count} valid of ${result.users.length} spreadsheet rows. Review the list before creating accounts.`;
    bulkCreateButton.disabled = result.valid_count === 0;
    bulkCreateButton.classList.toggle('hidden', result.valid_count === 0);
  } catch (error) {
    bulkUsersMessage.textContent = error.message;
    bulkUsersMessage.classList.add('error');
  } finally {
    bulkPreviewButton.disabled = false;
  }
});

function renderBulkUsersPreview(users) {
  bulkUsersPreview.replaceChildren();
  const table = document.createElement('table');
  table.className = 'bulk-users-table';
  const header = document.createElement('tr');
  ['Row', 'Name', 'Email', 'Department', 'Role', 'Validation'].forEach((label) => {
    const cell = document.createElement('th');
    cell.scope = 'col';
    cell.textContent = label;
    header.append(cell);
  });
  const head = document.createElement('thead');
  head.append(header);
  const body = document.createElement('tbody');
  users.forEach((user) => {
    const row = document.createElement('tr');
    [user.row, user.name, user.email, user.department, user.role].forEach((value) => {
      const cell = document.createElement('td');
      cell.textContent = value ?? '';
      row.append(cell);
    });
    const validation = document.createElement('td');
    validation.className = user.valid ? 'bulk-valid' : 'bulk-invalid';
    validation.textContent = user.valid ? 'Ready to create' : user.errors.join(' ');
    row.append(validation);
    body.append(row);
  });
  table.append(head, body);
  bulkUsersPreview.append(table);
  bulkUsersPreview.classList.remove('hidden');
}

bulkCreateButton.addEventListener('click', async () => {
  const validUsers = bulkPreviewUsers
    .filter((user) => user.valid)
    .map(({ name, email, department, role }) => ({ name, email, department, role }));
  if (!validUsers.length) return;
  bulkCreateButton.disabled = true;
  bulkUsersMessage.textContent = 'Creating accounts and sending invitations…';
  bulkUsersMessage.classList.remove('error');
  try {
    const result = await apiFetch('/api/admin/users/bulk', {
      method: 'POST',
      body: JSON.stringify({ users: validUsers }),
    });
    bulkUsersMessage.textContent =
      `${result.created_count} accounts created and invited; ${result.failed_count} failed.`;
    renderBulkCreateResults(result.results);
    bulkCreateButton.classList.add('hidden');
    bulkPreviewUsers = [];
    await loadUsers();
  } catch (error) {
    bulkUsersMessage.textContent = error.message;
    bulkUsersMessage.classList.add('error');
    bulkCreateButton.disabled = false;
  }
});

function renderBulkCreateResults(results) {
  const list = document.createElement('ul');
  list.className = 'bulk-create-results';
  results.forEach((result) => {
    const item = document.createElement('li');
    item.className = result.status === 'created' ? 'bulk-valid' : 'bulk-invalid';
    item.textContent = result.status === 'created'
      ? `${result.email}: invitation sent.`
      : `${result.email}: ${result.message}`;
    list.append(item);
  });
  bulkUsersPreview.replaceChildren(list);
  bulkUsersPreview.classList.remove('hidden');
}

async function loadUsers() {
  usersList.replaceChildren();
  const loading = document.createElement('p');
  loading.className = 'sources-empty';
  loading.textContent = 'Loading team accounts…';
  usersList.append(loading);
  try {
    const { users } = await apiFetch('/api/admin/users');
    usersList.replaceChildren();
    if (!users.length) {
      const empty = document.createElement('p');
      empty.className = 'sources-empty';
      empty.textContent = 'No team accounts found.';
      usersList.append(empty);
      return;
    }
    users.forEach((user) => {
      const row = document.createElement('article');
      row.className = 'user-row';
      const info = document.createElement('div');
      info.className = 'user-info';
      const name = document.createElement('strong');
      name.textContent = user.name;
      const detail = document.createElement('span');
      detail.textContent = `${user.email} · ${user.department} · ${user.role}`;
      info.append(name, detail);

      const active = document.createElement('span');
      active.className = `user-state${user.is_active ? '' : ' inactive'}`;
      active.textContent = user.is_active ? 'Active' : 'Inactive';
      const state = document.createElement('div');
      state.className = 'user-status';
      state.append(active);
      if (user.activation_pending) {
        const pending = document.createElement('span');
        pending.className = 'password-required';
        pending.textContent = 'Pending activation';
        state.append(pending);
      } else if (user.must_change_password) {
        const pending = document.createElement('span');
        pending.className = 'password-required';
        pending.textContent = 'Password change required';
        state.append(pending);
      }
      row.append(info, state);

      if (user.id !== currentUser.id) {
        const actions = document.createElement('div');
        actions.className = 'user-actions';
        if (user.activation_pending) {
          const resend = document.createElement('button');
          resend.className = 'user-toggle';
          resend.type = 'button';
          resend.textContent = 'Resend invitation';
          resend.addEventListener('click', () => resendActivation(user, resend));
          actions.append(resend);
        } else {
          if (user.is_active) {
            const reset = document.createElement('button');
            reset.className = 'user-toggle';
            reset.type = 'button';
            reset.textContent = 'Send reset link';
            reset.setAttribute('aria-label', `Email a password reset link to ${user.name}`);
            reset.addEventListener('click', () => requestAdminPasswordReset(user, reset));
            actions.append(reset);
          }
          const toggle = document.createElement('button');
          toggle.className = 'user-toggle';
          toggle.type = 'button';
          toggle.textContent = user.is_active ? 'Deactivate' : 'Activate';
          toggle.setAttribute(
            'aria-label',
            `${user.is_active ? 'Deactivate' : 'Activate'} ${user.name}`,
          );
          toggle.addEventListener('click', () => setUserActive(user, toggle));
          actions.append(toggle);
        }

        const remove = document.createElement('button');
        remove.className = 'user-toggle user-delete';
        remove.type = 'button';
        remove.textContent = 'Delete';
        remove.setAttribute('aria-label', `Permanently delete ${user.name}`);
        remove.addEventListener('click', () => deleteUserAccount(user, remove));
        actions.append(remove);
        row.append(actions);
      }
      usersList.append(row);
    });
  } catch (error) {
    usersList.replaceChildren();
    const message = document.createElement('p');
    message.className = 'sources-empty error';
    message.textContent = error.message;
    usersList.append(message);
  }
}

async function resendActivation(user, button) {
  button.disabled = true;
  try {
    await apiFetch(`/api/admin/users/${encodeURIComponent(user.id)}/activation`, {
      method: 'POST',
    });
    setAdminMessage(`A new activation email was sent to ${user.email}.`);
  } catch (error) {
    setAdminMessage(error.message, true);
  } finally {
    button.disabled = false;
  }
}

async function deleteUserAccount(user, button) {
  const confirmed = window.confirm(
    `Permanently delete ${user.name} (${user.email})? This cannot be undone. Historical audit and SOP-review records will be retained.`,
  );
  if (!confirmed) return;
  button.disabled = true;
  try {
    await apiFetch(`/api/admin/users/${encodeURIComponent(user.id)}`, {
      method: 'DELETE',
    });
    setAdminMessage(`Account ${user.email} was permanently deleted.`);
    await loadUsers();
  } catch (error) {
    setAdminMessage(error.message, true);
    button.disabled = false;
  }
}

async function requestAdminPasswordReset(user, button) {
  button.disabled = true;
  try {
    await apiFetch(
      `/api/admin/users/${encodeURIComponent(user.id)}/password-reset`,
      { method: 'POST' },
    );
    setAdminMessage(`A password reset link was emailed to ${user.email}.`);
  } catch (error) {
    setAdminMessage(error.message, true);
  } finally {
    button.disabled = false;
  }
}

async function setUserActive(user, button) {
  button.disabled = true;
  try {
    await apiFetch(`/api/admin/users/${encodeURIComponent(user.id)}/active`, {
      method: 'PATCH',
      body: JSON.stringify({ is_active: !user.is_active }),
    });
    await loadUsers();
  } catch (error) {
    setAdminMessage(error.message, true);
    button.disabled = false;
  }
}

async function loadAuditLogs() {
  refreshAuditButton.disabled = true;
  auditList.replaceChildren();
  const loading = document.createElement('p');
  loading.className = 'sources-empty';
  loading.textContent = 'Loading audit activity…';
  auditList.append(loading);
  try {
    const { audit_logs: logs } = await apiFetch('/api/admin/audit-logs?limit=25');
    auditList.replaceChildren();
    if (!logs.length) {
      const empty = document.createElement('p');
      empty.className = 'sources-empty';
      empty.textContent = 'No queries have been recorded yet.';
      auditList.append(empty);
      return;
    }
    logs.forEach((log) => {
      const item = document.createElement('article');
      item.className = 'audit-entry';
      const heading = document.createElement('strong');
      heading.textContent = `${log.email} · ${log.department}`;
      const question = document.createElement('p');
      question.textContent = log.question;
      const result = document.createElement('p');
      result.className = 'meta';
      const outcome = log.missing_sop
        ? 'No approved match'
        : log.success
          ? `SOPs: ${log.retrieved_sops.join(', ')}`
          : 'Access denied';
      result.textContent = `${log.created_at} · ${outcome}`;
      item.append(heading, question, result);
      auditList.append(item);
    });
  } catch (error) {
    auditList.replaceChildren();
    const message = document.createElement('p');
    message.className = 'sources-empty error';
    message.textContent = error.message;
    auditList.append(message);
  } finally {
    refreshAuditButton.disabled = false;
  }
}

refreshAuditButton.addEventListener('click', loadAuditLogs);

async function loadDocumentCategories() {
  try {
    const { categories } = await apiFetch('/api/document-categories');
    documentCategories = categories;
    populateCategorySelect(libraryCategoryFilter, true);
    populateCategorySelect(adminDocumentCategory, true);
    populateCategorySelect(sopCategorySelect, false, 'Choose category or flag for review');
    populateCategorySelect(
      documentBulkDefaultCategory,
      true,
      'Choose a batch category…',
    );
    renderBulkMetadataRows();
  } catch (error) {
    categoryMessage.textContent = error.message;
    categoryMessage.classList.add('error');
  }
}

function populateCategorySelect(select, includeAll, placeholder = 'All categories') {
  if (!select) return;
  const selected = select.value;
  select.replaceChildren();
  if (includeAll) {
    const all = document.createElement('option');
    all.value = '';
    all.textContent = placeholder;
    select.append(all);
  } else {
    const blank = document.createElement('option');
    blank.value = '';
    blank.textContent = placeholder;
    select.append(blank);
  }
  documentCategories.forEach((category) => {
    const option = document.createElement('option');
    option.value = category.id;
    option.textContent = category.name;
    select.append(option);
  });
  if ([...select.options].some((option) => option.value === selected)) {
    select.value = selected;
  }
}

async function loadAdminCategories() {
  try {
    const { categories } = await apiFetch('/api/admin/document-categories');
    categoryList.replaceChildren();
    categories.forEach((category) => {
      const row = document.createElement('article');
      row.className = 'category-row';
      const detail = document.createElement('div');
      const name = document.createElement('strong');
      name.textContent = category.name;
      const description = document.createElement('span');
      description.textContent =
        `${category.description || 'No description'} · ${category.document_count} documents`;
      detail.append(name, description);
      const actions = document.createElement('div');
      actions.className = 'user-actions';
      const edit = document.createElement('button');
      edit.type = 'button';
      edit.className = 'user-toggle';
      edit.textContent = 'Rename / edit';
      edit.addEventListener('click', async () => {
        const nameValue = window.prompt('Category name:', category.name);
        if (nameValue === null) return;
        const descriptionValue = window.prompt(
          'Category description:',
          category.description || '',
        );
        if (descriptionValue === null) return;
        try {
          await apiFetch(`/api/admin/document-categories/${encodeURIComponent(category.id)}`, {
            method: 'PATCH',
            body: JSON.stringify({ name: nameValue, description: descriptionValue }),
          });
          await loadAdminCategories();
          await loadDocumentCategories();
        } catch (error) {
          categoryMessage.textContent = error.message;
          categoryMessage.classList.add('error');
        }
      });
      actions.append(edit);
      const toggle = document.createElement('button');
      toggle.type = 'button';
      toggle.className = 'user-toggle';
      toggle.textContent = category.is_active ? 'Archive' : 'Restore';
      toggle.addEventListener('click', async () => {
        const action = category.is_active ? 'archive' : 'restore';
        try {
          await apiFetch(
            `/api/admin/document-categories/${encodeURIComponent(category.id)}/${action}`,
            { method: 'POST' },
          );
          await loadAdminCategories();
          await loadDocumentCategories();
        } catch (error) {
          categoryMessage.textContent = error.message;
          categoryMessage.classList.add('error');
        }
      });
      actions.append(toggle);
      row.append(detail, actions);
      categoryList.append(row);
    });
  } catch (error) {
    categoryList.textContent = error.message;
  }
}

categoryCreateForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  const name = document.getElementById('category-name').value.trim();
  const description = document.getElementById('category-description').value.trim();
  try {
    await apiFetch('/api/admin/document-categories', {
      method: 'POST',
      body: JSON.stringify({ name, description }),
    });
    categoryCreateForm.reset();
    categoryMessage.textContent = 'Category created.';
    categoryMessage.classList.remove('error');
    await loadAdminCategories();
    await loadDocumentCategories();
  } catch (error) {
    categoryMessage.textContent = error.message;
    categoryMessage.classList.add('error');
  }
});

documentBulkFiles.addEventListener('change', renderBulkMetadataRows);
documentBulkDefaultCategory.addEventListener('change', () => {
  documentBulkMetadata
    .querySelectorAll('[data-field="category_id"]')
    .forEach((select) => {
      select.value = documentBulkDefaultCategory.value;
    });
});
documentBulkDefaultDepartment.addEventListener('input', () => {
    documentBulkMetadata
      .querySelectorAll('[data-field="department"]')
      .forEach((input) => {
        input.value = documentBulkDefaultDepartment.value;
      });
});

function renderBulkMetadataRows() {
  documentBulkMetadata.replaceChildren();
  const files = [...documentBulkFiles.files];
  documentBulkSubmit.disabled = files.length === 0 || files.length > 30;
  if (!files.length) return;
  if (files.length > 30) {
    documentBulkMessage.textContent = 'Choose no more than 30 files per batch.';
    documentBulkMessage.classList.add('error');
    return;
  }
  const table = document.createElement('div');
  table.className = 'document-bulk-rows';
  files.forEach((file, index) => {
    const row = document.createElement('fieldset');
    row.className = 'document-bulk-row';
    const legend = document.createElement('legend');
    legend.textContent = `${index + 1}. ${file.name} (${formatFileSize(file.size)})`;
    row.append(legend);
    const fields = [
      ['title', 'Title', file.name.replace(/\.[^.]+$/, ''), true, 'text'],
      ['sop_id', 'SOP ID (optional)', suggestSopIdFromFilename(file.name), false, 'text'],
      ['category_id', 'Category', documentBulkDefaultCategory.value, true, 'select'],
      ['document_type', 'Document type', 'SOP', true, 'text'],
      ['department', 'Department', documentBulkDefaultDepartment.value, true, 'text'],
      ['owner', 'Owner', currentUser.name, true, 'text'],
      ['version', 'Version', '1.0', true, 'text'],
      ['effective_date', 'Effective date', new Date().toISOString().slice(0, 10), true, 'date'],
      ['tags', 'Search tags (comma-separated)', '', false, 'text'],
    ];
    const grid = document.createElement('div');
    grid.className = 'document-bulk-fields';
    fields.forEach(([name, label, value, required, type]) => {
      const wrapper = document.createElement('div');
      const fieldLabel = document.createElement('label');
      fieldLabel.textContent = label;
      const input = type === 'select'
        ? document.createElement('select')
        : document.createElement('input');
      input.dataset.field = name;
      input.required = required;
      if (type === 'select') {
        const placeholder = document.createElement('option');
        placeholder.value = '';
        placeholder.textContent = 'Choose category…';
        input.append(placeholder);
        documentCategories.forEach((category) => {
          const option = document.createElement('option');
          option.value = category.id;
          option.textContent = category.name;
          input.append(option);
        });
        input.value = value;
      } else {
        input.type = type;
        input.value = value;
        if (name === 'sop_id') {
          input.maxLength = 120;
          input.placeholder = 'Detected from file or generated automatically';
        }
        if (name === 'title') input.maxLength = 200;
      }
      wrapper.append(fieldLabel, input);
      grid.append(wrapper);
    });
    row.append(grid);
    table.append(row);
  });
  documentBulkMetadata.append(table);
  documentBulkMessage.textContent =
    `${files.length} file(s) ready. Set a batch category or choose one per file; IDs are detected or generated automatically.`;
  documentBulkMessage.classList.remove('error');
}

function suggestSopIdFromFilename(filename) {
  const match = filename.match(
    /\bSOP(?:[-_][A-Z0-9]+)*[-_]\d{1,6}[A-Z]?(?=[-_.\s]|$)/i,
  );
  return match ? match[0].replaceAll('_', '-') : '';
}

function formatFileSize(bytes) {
  return bytes < 1024 * 1024
    ? `${Math.max(1, Math.ceil(bytes / 1024))} KB`
    : `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

documentBulkSubmit.addEventListener('click', () => {
  const files = [...documentBulkFiles.files];
  const rows = [...documentBulkMetadata.querySelectorAll('.document-bulk-row')];
  if (!files.length || rows.length !== files.length) return;
  const metadata = rows.map((row) => {
    const entry = {};
    row.querySelectorAll('[data-field]').forEach((input) => {
      const value = input.value.trim();
      entry[input.dataset.field] = input.dataset.field === 'tags'
        ? value.split(',').map((tag) => tag.trim()).filter(Boolean)
        : value;
    });
    entry.review_cycle_days = null;
    return entry;
  });
  const formData = new FormData();
  files.forEach((file) => formData.append('files', file, file.name));
  formData.append('metadata', JSON.stringify(metadata));
  documentBulkSubmit.disabled = true;
  documentBulkResults.replaceChildren();
  documentUploadProgress.value = 0;
  documentUploadProgress.classList.remove('hidden');
  documentBulkMessage.textContent = 'Uploading documents…';
  documentBulkMessage.classList.remove('error');

  const request = new XMLHttpRequest();
  request.open('POST', '/api/admin/documents/bulk-upload');
  request.setRequestHeader('Authorization', `Bearer ${accessToken}`);
  request.upload.addEventListener('progress', (event) => {
    if (!event.lengthComputable) return;
    documentUploadProgress.value = Math.round((event.loaded / event.total) * 100);
    documentBulkMessage.textContent =
      `Uploading ${formatFileSize(event.loaded)} of ${formatFileSize(event.total)}…`;
  });
  request.addEventListener('load', async () => {
    let result;
    try {
      result = JSON.parse(request.responseText);
    } catch {
      documentBulkMessage.textContent = 'The server returned an unexpected response.';
      documentBulkMessage.classList.add('error');
      documentBulkSubmit.disabled = false;
      return;
    }
    if (request.status < 200 || request.status >= 300) {
      documentBulkMessage.textContent = result.detail || 'The upload batch failed.';
      documentBulkMessage.classList.add('error');
      documentBulkSubmit.disabled = false;
      return;
    }
    renderDocumentUploadResults(result.results);
    documentBulkMessage.textContent =
      `${result.uploaded_count} uploaded for review; ${result.duplicate_count} duplicate; ` +
      `${result.needs_attention_count} need attention.`;
    documentBulkFiles.value = '';
    documentBulkMetadata.replaceChildren();
    documentBulkSubmit.disabled = true;
    await Promise.all([
      loadSops(),
      loadDocumentCatalog(),
      loadFailedUploads(),
      loadDocumentAudit(),
      loadApprovedSops(),
    ]);
  });
  request.addEventListener('error', () => {
    documentBulkMessage.textContent = 'Upload interrupted. Check the failed uploads queue.';
    documentBulkMessage.classList.add('error');
    documentBulkSubmit.disabled = false;
  });
  request.addEventListener('loadend', () => {
    documentUploadProgress.classList.add('hidden');
  });
  request.send(formData);
});

function renderDocumentUploadResults(results) {
  documentBulkResults.replaceChildren();
  results.forEach((result) => {
    const item = document.createElement('li');
    item.className = result.status === 'uploaded'
      ? 'bulk-valid'
      : result.status === 'duplicate' ? 'bulk-duplicate' : 'bulk-invalid';
    item.textContent = result.status === 'uploaded'
      ? `${result.filename}: queued for review as ${result.sop_id} (${result.category}).`
      : `${result.filename}: ${result.status === 'duplicate' ? 'duplicate' : 'needs attention'} — ${result.message}`;
    documentBulkResults.append(item);
  });
}

sopUploadForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  sopUploadButton.disabled = true;
  setSopUploadMessage('Uploading and extracting the document…');
  try {
    const result = await apiFetch('/api/admin/sops/upload', {
      method: 'POST',
      body: new FormData(sopUploadForm),
    });
    setSopUploadMessage(`Uploaded ${result.sop_id || 'SOP'} for review.`);
    sopUploadForm.reset();
    await loadSops();
  } catch (error) {
    setSopUploadMessage(error.message, true);
  } finally {
    sopUploadButton.disabled = false;
  }
});

async function loadSops() {
  refreshSopsButton.disabled = true;
  sopList.replaceChildren();
  const loading = document.createElement('p');
  loading.className = 'sources-empty';
  loading.textContent = 'Loading SOP versions…';
  sopList.append(loading);
  try {
    const { sops } = await apiFetch('/api/admin/sops');
    sopList.replaceChildren();
    if (!sops.length) {
      const empty = document.createElement('p');
      empty.className = 'sources-empty';
      empty.textContent = 'No uploaded SOP versions yet.';
      sopList.append(empty);
      return;
    }
    sops.forEach((sop) => {
      const row = document.createElement('article');
      row.className = 'sop-row';
      const info = document.createElement('div');
      info.className = 'sop-info';
      const title = document.createElement('strong');
      title.textContent = `${sop.sop_id} · ${sop.title}`;
      const detail = document.createElement('span');
      detail.textContent = `${sop.department} · v${sop.version} · ${sop.section_count} sections · Effective ${sop.effective_date}`;
      const status = document.createElement('span');
      status.className = `sop-status status-${sop.status}`;
      status.textContent = sop.status.replaceAll('_', ' ');
      info.append(title, detail, status);
      row.append(info);
      const preview = document.createElement('div');
      preview.className = 'sop-preview hidden';
      const previewButton = document.createElement('button');
      previewButton.type = 'button';
      previewButton.className = 'user-toggle';
      previewButton.textContent = 'Preview sections';
      previewButton.setAttribute('aria-expanded', 'false');
      previewButton.addEventListener('click', async () => {
        if (!preview.classList.contains('hidden')) {
          preview.classList.add('hidden');
          previewButton.setAttribute('aria-expanded', 'false');
          previewButton.textContent = 'Preview sections';
          return;
        }
        previewButton.disabled = true;
        try {
          const result = await apiFetch(
            `/api/admin/sops/${encodeURIComponent(sop.id)}`,
          );
          preview.replaceChildren();
          result.sections.forEach((section) => {
            const sectionCard = document.createElement('section');
            sectionCard.className = 'sop-preview-section';
            const heading = document.createElement('h4');
            heading.textContent = section.heading;
            const content = document.createElement('p');
            content.textContent = section.content;
            sectionCard.append(heading, content);
            preview.append(sectionCard);
          });
          preview.classList.remove('hidden');
          previewButton.setAttribute('aria-expanded', 'true');
          previewButton.textContent = 'Hide sections';
        } catch (error) {
          setSopUploadMessage(error.message, true);
        } finally {
          previewButton.disabled = false;
        }
      });
      row.append(previewButton, preview);
      if (sop.status === 'pending_review') {
        const actions = document.createElement('div');
        actions.className = 'sop-actions';
        [
          ['approve', 'Approve', 'button-primary'],
          ['reject', 'Reject', 'button-quiet'],
        ].forEach(([action, label, style]) => {
          const button = document.createElement('button');
          button.type = 'button';
          button.className = `button ${style}`;
          button.textContent = label;
          button.addEventListener('click', () => reviewSop(sop, action, button));
          actions.append(button);
        });
        row.append(actions);
      }
      sopList.append(row);
    });
  } catch (error) {
    sopList.replaceChildren();
    const message = document.createElement('p');
    message.className = 'sources-empty error';
    message.textContent = error.message;
    sopList.append(message);
  } finally {
    refreshSopsButton.disabled = false;
  }
}

async function reviewSop(sop, action, button) {
  button.disabled = true;
  const reviewNote = window.prompt(`Optional review note for ${action}:`);
  if (reviewNote === null) {
    button.disabled = false;
    return;
  }
  const body = new FormData();
  body.set('action', action);
  body.set('review_note', reviewNote);
  try {
    await apiFetch(`/api/admin/sops/${encodeURIComponent(sop.id)}/review`, {
      method: 'POST',
      body,
    });
    const result = action === 'approve' ? 'approved' : 'rejected';
    setSopUploadMessage(`${sop.sop_id} ${result} successfully.`);
    await loadSops();
  } catch (error) {
    setSopUploadMessage(error.message, true);
    button.disabled = false;
  }
}

refreshSopsButton.addEventListener('click', loadSops);

async function loadDocumentCatalog() {
  const parameters = new URLSearchParams();
  if (adminDocumentSearch.value.trim()) parameters.set('query', adminDocumentSearch.value.trim());
  if (adminDocumentCategory.value) parameters.set('category_id', adminDocumentCategory.value);
  if (adminDocumentStatus.value) parameters.set('status', adminDocumentStatus.value);
  if (adminDocumentTag.value.trim()) parameters.set('tag', adminDocumentTag.value.trim());
  if (adminDocumentDateAfter.value) parameters.set('effective_after', adminDocumentDateAfter.value);
  if (adminDocumentDateBefore.value) parameters.set('effective_before', adminDocumentDateBefore.value);
  if (adminShowDeleted.checked) parameters.set('include_deleted', 'true');
  const query = parameters.toString();
  documentCatalogList.replaceChildren();
  try {
    const result = await apiFetch(`/api/admin/sops${query ? `?${query}` : ''}`);
    if (!result.sops.length) {
      const empty = document.createElement('p');
      empty.className = 'sources-empty';
      empty.textContent = 'No documents match these filters.';
      documentCatalogList.append(empty);
      return;
    }
    result.sops.forEach((documentRecord) => {
      const row = document.createElement('article');
      row.className = 'sop-row';
      const info = document.createElement('div');
      info.className = 'sop-info';
      const title = document.createElement('strong');
      title.textContent = `${documentRecord.sop_id} · ${documentRecord.title}`;
      const detail = document.createElement('span');
      detail.textContent = [
        documentRecord.category_name || 'Needs category review',
        documentRecord.document_type,
        documentRecord.department,
        `v${documentRecord.version}`,
        `Effective ${documentRecord.effective_date}`,
        (documentRecord.tags || []).join(', '),
      ].filter(Boolean).join(' · ');
      const state = document.createElement('span');
      state.className = `sop-status status-${documentRecord.deleted_at ? 'deleted' : documentRecord.status}`;
      state.textContent = documentRecord.deleted_at ? 'deleted' : documentRecord.status.replaceAll('_', ' ');
      info.append(title, detail, state);
      row.append(info);
      const actions = document.createElement('div');
      actions.className = 'sop-actions document-actions';
      if (documentRecord.deleted_at) {
        actions.append(
          documentActionButton('Restore', () => restoreDocument(documentRecord)),
          documentActionButton('Permanently delete', () => permanentlyDeleteDocument(documentRecord), 'user-delete'),
        );
      } else {
        actions.append(
          documentActionButton('Download', () => downloadFile(
            `/api/documents/${encodeURIComponent(documentRecord.id)}/download`,
            documentRecord.original_filename,
          )),
          documentActionButton('Replace with new version', () => selectDocumentReplacement(documentRecord)),
          documentActionButton('Edit metadata', () => editDocumentMetadata(documentRecord)),
        );
        if (documentRecord.status === 'pending_review' && !documentRecord.category_review_required) {
          actions.append(documentActionButton('Approve', () => reviewDocument(documentRecord, 'approve')));
          actions.append(documentActionButton('Reject', () => reviewDocument(documentRecord, 'reject')));
        }
        if (documentRecord.status === 'approved') {
          actions.append(documentActionButton('Archive', () => reviewDocument(documentRecord, 'archive')));
        }
        actions.append(documentActionButton('Delete', () => softDeleteDocument(documentRecord), 'user-delete'));
      }
      row.append(actions);
      documentCatalogList.append(row);
    });
  } catch (error) {
    const message = document.createElement('p');
    message.className = 'sources-empty error';
    message.textContent = error.message;
    documentCatalogList.replaceChildren(message);
  }
}

function documentActionButton(label, action, extraClass = '') {
  const button = document.createElement('button');
  button.type = 'button';
  button.className = `button button-quiet ${extraClass}`.trim();
  button.textContent = label;
  const descriptions = {
    'Download': 'Download the original file.',
    'Replace with new version': 'Upload a replacement as a new version for review. The current approved version stays available until approval.',
    'Edit metadata': 'Change title, category, department, owner, effective date, or search tags.',
    'Approve': 'Publish this document so authorized staff can use it.',
    'Reject': 'Reject this submission so it is not published.',
    'Archive': 'Hide this approved document from staff without deleting its history.',
    'Delete': 'Move this document to Deleted. An administrator can restore it later.',
    'Restore': 'Return this deleted document to its previous state.',
    'Permanently delete': 'Permanently remove the document file and extracted content.',
  };
  if (descriptions[label]) button.title = descriptions[label];
  button.addEventListener('click', action);
  return button;
}

function selectDocumentReplacement(documentRecord) {
  const input = document.createElement('input');
  input.type = 'file';
  input.accept = '.md,.pdf,.docx';
  input.hidden = true;
  input.addEventListener('change', async () => {
    const file = input.files[0];
    input.remove();
    if (!file) return;
    const version = window.prompt('New version number:', '');
    if (version === null || !version.trim()) return;
    const effectiveDate = window.prompt(
      'New effective date (YYYY-MM-DD):',
      new Date().toISOString().slice(0, 10),
    );
    if (effectiveDate === null) return;
    const formData = new FormData();
    formData.set('file', file, file.name);
    formData.set('version', version.trim());
    formData.set('effective_date', effectiveDate.trim());
    try {
      const result = await apiFetch(
        `/api/admin/documents/${encodeURIComponent(documentRecord.id)}/replace`,
        { method: 'POST', body: formData },
      );
      window.alert(result.message);
      await loadDocumentCatalog();
    } catch (error) {
      window.alert(error.message);
    }
  }, { once: true });
  document.body.append(input);
  input.click();
}

async function editDocumentMetadata(documentRecord) {
  const categoryChoice = window.prompt(
    `Category name (${documentCategories.map((category) => category.name).join(', ')}):`,
    documentRecord.category_name || '',
  );
  if (categoryChoice === null) return;
  const category = documentCategories.find(
    (item) => item.name.toLocaleLowerCase() === categoryChoice.trim().toLocaleLowerCase(),
  );
  if (!category) {
    window.alert('Enter the exact name of an active category.');
    return;
  }
  const fields = [
    ['title', 'Document title', documentRecord.title],
    ['document_type', 'Document type', documentRecord.document_type],
    ['department', 'Department', documentRecord.department],
    ['owner', 'Owner', documentRecord.owner],
    ['effective_date', 'Effective date (YYYY-MM-DD)', documentRecord.effective_date],
    ['tags', 'Search tags, comma-separated', (documentRecord.tags || []).join(', ')],
  ];
  const payload = { category_id: category.id };
  for (const [key, label, value] of fields) {
    const answer = window.prompt(`${label}:`, value || '');
    if (answer === null) return;
    if (key === 'tags') {
      payload.tags = answer.split(',').map((tag) => tag.trim()).filter(Boolean);
    } else {
      payload[key] = answer.trim();
    }
  }
  try {
    await apiFetch(`/api/admin/documents/${encodeURIComponent(documentRecord.id)}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    });
    await loadDocumentCatalog();
    await loadApprovedSops();
  } catch (error) {
    window.alert(error.message);
  }
}

async function reviewDocument(documentRecord, action) {
  if (!window.confirm(`${action} ${documentRecord.sop_id} · ${documentRecord.title}?`)) return;
  const body = new FormData();
  body.set('action', action);
  try {
    await apiFetch(`/api/admin/sops/${encodeURIComponent(documentRecord.id)}/review`, {
      method: 'POST',
      body,
    });
    await Promise.all([loadDocumentCatalog(), loadSops(), loadApprovedSops()]);
  } catch (error) {
    window.alert(error.message);
  }
}

async function softDeleteDocument(documentRecord) {
  if (!window.confirm(`Move "${documentRecord.title}" to Deleted? It can be restored by an administrator.`)) return;
  try {
    await apiFetch(`/api/admin/documents/${encodeURIComponent(documentRecord.id)}`, {
      method: 'DELETE',
    });
    await Promise.all([loadDocumentCatalog(), loadApprovedSops()]);
  } catch (error) {
    window.alert(error.message);
  }
}

async function restoreDocument(documentRecord) {
  try {
    await apiFetch(`/api/admin/documents/${encodeURIComponent(documentRecord.id)}/restore`, {
      method: 'POST',
    });
    await loadDocumentCatalog();
  } catch (error) {
    window.alert(error.message);
  }
}

async function permanentlyDeleteDocument(documentRecord) {
  const firstConfirm = window.confirm(
    `Permanently remove the original file and extracted text for "${documentRecord.title}"? Audit metadata will remain.`,
  );
  if (!firstConfirm) return;
  const secondConfirm = window.prompt('Type DELETE to confirm permanent removal:');
  if (secondConfirm !== 'DELETE') return;
  try {
    await apiFetch(
      `/api/admin/documents/${encodeURIComponent(documentRecord.id)}/permanent?confirm=true`,
      { method: 'DELETE' },
    );
    await loadDocumentCatalog();
  } catch (error) {
    window.alert(error.message);
  }
}

async function downloadFile(url, filename) {
  try {
    const response = await fetch(url, {
      headers: { Authorization: `Bearer ${accessToken}` },
    });
    if (!response.ok) {
      const data = await response.json();
      throw new Error(data.detail || 'The file could not be downloaded.');
    }
    const blob = await response.blob();
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = filename || 'document';
    link.click();
    URL.revokeObjectURL(link.href);
  } catch (error) {
    window.alert(error.message);
  }
}

async function loadFailedUploads() {
  failedUploadList.replaceChildren();
  try {
    const { failures } = await apiFetch('/api/admin/document-upload-failures');
    if (!failures.length) {
      const empty = document.createElement('p');
      empty.className = 'sources-empty';
      empty.textContent = 'No unresolved failed uploads.';
      failedUploadList.append(empty);
      return;
    }
    failures.forEach((failure) => {
      const row = document.createElement('article');
      row.className = 'sop-row';
      const detail = document.createElement('div');
      detail.className = 'sop-info';
      const title = document.createElement('strong');
      title.textContent = failure.original_filename;
      const message = document.createElement('span');
      message.textContent =
        `${failure.user_message} · uploaded by ${failure.uploaded_by} · ${failure.created_at}`;
      detail.append(title, message);
      const actions = document.createElement('div');
      actions.className = 'sop-actions';
      const chooseReplacement = () => {
        const input = document.createElement('input');
        input.type = 'file';
        input.accept = '.md,.pdf,.docx';
        input.hidden = true;
        input.addEventListener('change', async () => {
          const file = input.files[0];
          input.remove();
          if (file) await retryFailedUpload(failure, file);
        }, { once: true });
        document.body.append(input);
        input.click();
      };
      if (failure.has_original) {
        actions.append(
          documentActionButton('Download retained original', () => downloadFile(
            `/api/admin/document-upload-failures/${encodeURIComponent(failure.id)}/download`,
            failure.original_filename,
          )),
          documentActionButton('Correct metadata and retry', () => retryFailedUpload(failure)),
          documentActionButton('Choose replacement file', chooseReplacement),
        );
      } else {
        const unavailable = document.createElement('span');
        unavailable.className = 'meta';
        unavailable.textContent = 'No usable original is retained. Choose a supported file to retry.';
        actions.append(unavailable, documentActionButton('Choose replacement file', chooseReplacement));
      }
      actions.append(documentActionButton('Dismiss', async () => {
        if (!window.confirm(`Dismiss failed upload ${failure.original_filename}?`)) return;
        try {
          await apiFetch(
            `/api/admin/document-upload-failures/${encodeURIComponent(failure.id)}`,
            { method: 'DELETE' },
          );
          await loadFailedUploads();
        } catch (error) {
          window.alert(error.message);
        }
      }, 'user-delete'));
      row.append(detail, actions);
      failedUploadList.append(row);
    });
  } catch (error) {
    const message = document.createElement('p');
    message.className = 'sources-empty error';
    message.textContent = error.message;
    failedUploadList.append(message);
  }
}

async function retryFailedUpload(failure, replacementFile = null) {
  const metadata = { ...failure.metadata };
  const categoryChoices = documentCategories.map((category) => category.name).join(', ');
  const categoryChoice = window.prompt(
    `Active category (${categoryChoices}):`,
    documentCategories.find((category) => category.id === metadata.category_id)?.name || '',
  );
  if (categoryChoice === null) return;
  const category = documentCategories.find(
    (item) => item.name.toLocaleLowerCase() === categoryChoice.trim().toLocaleLowerCase(),
  );
  if (!category) {
    window.alert('Enter the exact name of an active category.');
    return;
  }
  metadata.category_id = category.id;
  const requiredFields = [
    ['sop_id', 'Document ID'],
    ['title', 'Title'],
    ['document_type', 'Document type'],
    ['department', 'Department'],
    ['owner', 'Owner'],
    ['version', 'Version'],
    ['effective_date', 'Effective date (YYYY-MM-DD)'],
  ];
  for (const [key, label] of requiredFields) {
    const value = window.prompt(`${label}:`, metadata[key] || '');
    if (value === null) return;
    metadata[key] = value.trim();
  }
  metadata.tags = Array.isArray(metadata.tags) ? metadata.tags : [];
  metadata.review_cycle_days = metadata.review_cycle_days || null;
  try {
    let url = `/api/admin/document-upload-failures/${encodeURIComponent(failure.id)}/retry`;
    let options = { method: 'POST', body: JSON.stringify({ metadata }) };
    if (replacementFile) {
      const formData = new FormData();
      formData.append('file', replacementFile);
      formData.append('metadata', JSON.stringify(metadata));
      url = `/api/admin/document-upload-failures/${encodeURIComponent(failure.id)}/replace`;
      options = { method: 'POST', body: formData };
    }
    await apiFetch(url, options);
    await Promise.all([loadFailedUploads(), loadDocumentCatalog()]);
  } catch (error) {
    window.alert(error.message);
    await loadFailedUploads();
  }
}

async function loadDocumentAudit() {
  const query = documentAuditSearch.value.trim();
  const parameters = new URLSearchParams({ limit: '100' });
  if (query) parameters.set('query', query);
  documentAuditList.replaceChildren();
  try {
    const { events } = await apiFetch(`/api/admin/document-audit?${parameters}`);
    if (!events.length) {
      const empty = document.createElement('p');
      empty.className = 'sources-empty';
      empty.textContent = 'No document activity matches this search.';
      documentAuditList.append(empty);
      return;
    }
    events.forEach((event) => {
      const row = document.createElement('article');
      row.className = 'audit-entry';
      const heading = document.createElement('strong');
      heading.textContent = `${event.actor_email} · ${event.action}`;
      const detail = document.createElement('p');
      const changes = JSON.stringify(event.details);
      detail.textContent = `${event.document_title || event.category_name || 'Document management'} · ${event.created_at} · ${changes}`;
      row.append(heading, detail);
      documentAuditList.append(row);
    });
  } catch (error) {
    const message = document.createElement('p');
    message.className = 'sources-empty error';
    message.textContent = error.message;
    documentAuditList.append(message);
  }
}

refreshDocumentCatalogButton.addEventListener('click', loadDocumentCatalog);
refreshFailedUploadsButton.addEventListener('click', loadFailedUploads);
searchDocumentAuditButton.addEventListener('click', loadDocumentAudit);
adminDocumentSearch.addEventListener('input', loadDocumentCatalog);
adminDocumentCategory.addEventListener('change', loadDocumentCatalog);
adminDocumentStatus.addEventListener('change', loadDocumentCatalog);
[
  adminDocumentTag,
  adminDocumentDateAfter,
  adminDocumentDateBefore,
].forEach((control) => control.addEventListener('change', loadDocumentCatalog));
adminShowDeleted.addEventListener('change', loadDocumentCatalog);

async function loadApprovedSops() {
  libraryList.replaceChildren();
  const loading = document.createElement('p');
  loading.className = 'sources-empty';
  loading.textContent = 'Loading approved procedures…';
  libraryList.append(loading);
  refreshLibraryButton.disabled = true;
  try {
    const parameters = new URLSearchParams();
    if (libraryCategoryFilter.value) parameters.set('category_id', libraryCategoryFilter.value);
    if (libraryTagFilter.value.trim()) parameters.set('tag', libraryTagFilter.value.trim());
    if (libraryDateAfter.value) parameters.set('effective_after', libraryDateAfter.value);
    if (libraryDateBefore.value) parameters.set('effective_before', libraryDateBefore.value);
    const query = parameters.toString();
    const result = await apiFetch(`/api/documents${query ? `?${query}` : ''}`);
    approvedSops = result.documents;
    renderApprovedSops();
  } catch (error) {
    libraryList.replaceChildren();
    const message = document.createElement('p');
    message.className = 'sources-empty error';
    message.textContent = error.message;
    libraryList.append(message);
  } finally {
    refreshLibraryButton.disabled = false;
  }
}

function renderApprovedSops() {
  const query = librarySearch.value.trim().toLocaleLowerCase();
  const visible = approvedSops.filter((sop) => (
    `${sop.sop_id} ${sop.title} ${sop.department} ${sop.category_name} ${sop.document_type} ${(sop.tags || []).join(' ')} ${sop.version}`
      .toLocaleLowerCase()
      .includes(query)
  ));
  libraryList.replaceChildren();
  if (!visible.length) {
    const empty = document.createElement('p');
    empty.className = 'sources-empty';
    empty.textContent = query
      ? 'No approved procedures match this search.'
      : 'No effective approved SOPs are available to your account.';
    libraryList.append(empty);
    return;
  }

  visible.forEach((sop) => {
    const item = document.createElement('article');
    item.className = 'library-item';
    const identity = document.createElement('div');
    identity.className = 'library-identity';
    const title = document.createElement('strong');
    title.textContent = sop.title;
    const sopId = document.createElement('span');
    sopId.textContent = sop.sop_id;
    identity.append(title, sopId);
    const metadata = document.createElement('div');
    metadata.className = 'library-metadata';
    [
      sop.category_name,
      sop.document_type,
      sop.department,
      `Version ${sop.version}`,
      `Effective ${sop.effective_date}`,
      ...(sop.tags || []).map((tag) => `#${tag}`),
    ].filter(Boolean)
      .forEach((value) => {
        const tag = document.createElement('span');
        tag.textContent = value;
        metadata.append(tag);
      });
    const actions = document.createElement('div');
    actions.className = 'library-document-actions';
    const download = document.createElement('button');
    download.type = 'button';
    download.className = 'button button-quiet';
    download.textContent = 'Download';
    download.addEventListener('click', () => downloadFile(
      sop.repository_path
        ? `/api/repository-documents/download?path=${encodeURIComponent(sop.repository_path)}`
        : `/api/documents/${encodeURIComponent(sop.id)}/download`,
      sop.original_filename,
    ));
    actions.append(download);
    const ask = document.createElement('button');
    ask.type = 'button';
    ask.className = 'button button-quiet library-ask';
    ask.textContent = 'Ask about this';
    ask.addEventListener('click', () => {
      if (currentUser.role === 'admin') departmentSelect.value = sop.department;
      questionInput.value = `What does ${sop.sop_id} say about this document?`;
      characterCount.textContent = `${questionInput.value.length} / 2000`;
      questionInput.focus();
      questionInput.scrollIntoView({ behavior: 'smooth', block: 'center' });
    });
    actions.append(ask);
    item.append(identity, metadata, actions);
    libraryList.append(item);
  });
}

librarySearch.addEventListener('input', renderApprovedSops);
[
  libraryCategoryFilter,
  libraryTagFilter,
  libraryDateAfter,
  libraryDateBefore,
].forEach((control) => control.addEventListener('change', loadApprovedSops));
refreshLibraryButton.addEventListener('click', loadApprovedSops);

if (window.location.pathname === '/activate' || window.location.pathname === '/reset-password') {
  showActivationPage();
}
