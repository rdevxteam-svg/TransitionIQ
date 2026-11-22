import React, { useState } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, Link, Navigate, NavLink, Route, Routes, useLocation, useParams, useSearchParams } from 'react-router-dom'
import { QueryClient, QueryClientProvider, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import './style.css'

const roleLabels = {
  employee: 'Employee',
  engagement_manager: 'Engagement Manager',
  transition_partner: 'Transition Partner',
  learning_team: 'L&D Team',
}
const engagementLabels = {
  receiving: 'Receiving Engagement Manager',
  releasing: 'Releasing Engagement Manager',
}
const sessionKey = ['session']
const states = {
  interested: 'Application submitted', declined: 'Declined', drafting: 'Preparing plan',
  planning: 'Plan ready to review', practice: 'Ready for assessment', assessing: 'Preparing feedback',
  sme_review: 'Transition Partner review', retry_requested: 'More preparation requested',
  fitment: 'Senior fit discussion', client_interview: 'Client interview', not_selected: 'Not selected',
  receiving_review: 'Receiving engagement review', receiving_hold: 'Receiving engagement hold',
  release_review: 'Release review', release_hold: 'Release hold', approved: 'Selected for project',
  onboarding: 'Knowledge transfer', readiness_assessment: 'Readiness assessment',
  activation_review: 'Final activation approval', activated: 'Active on project', allocated: 'Active on project',
  not_assessed: 'Awaiting assessment', awaiting_review: 'Awaiting human review', verified: 'Fit confirmed',
  needs_practice: 'More preparation needed',
}
const workspaces = {
  employee: {
    opportunities: true, transitions: 'My Transitions',
    description: 'See your career history, project experience, and transition applications.',
  },
  receiving: {
    opportunities: true, transitions: 'Transitions',
    description: 'Review candidates, confirm project access, and approve activation.',
  },
  releasing: {
    transitions: 'Release Reviews',
    description: 'Review and approve outgoing transitions.',
  },
  transition_partner: {
    transitions: 'Transition Reviews',
    description: 'Review assessment evidence and record senior fit discussions.',
  },
  learning_team: { learning: true },
}

const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })

async function request(path, { method = 'GET', data, account, signal, file, download = false } = {}) {
  const headers = {}
  if (method !== 'GET') headers['X-Transition-Request'] = '1'
  if (file) headers['Content-Type'] = 'application/octet-stream'
  else if (data !== undefined) headers['Content-Type'] = 'application/json'
  if (account) headers['X-Expected-Account'] = account
  const response = await fetch('/api' + path, {
    method,
    headers,
    signal,
    cache: 'no-store',
    body: file || (data === undefined ? undefined : JSON.stringify(data)),
  })
  if (response.status === 204) return null
  if (response.ok && download) return response.blob()
  const result = await response.json().catch(() => null)
  if (response.ok && result !== null) return result

  if (response.status === 401 && account) {
    void client.invalidateQueries({ queryKey: sessionKey })
  }
  const error = new Error(Array.isArray(result?.detail)
    ? result.detail.map(item => item.msg).join(' ')
    : result?.detail || 'The request could not be completed.')
  error.status = response.status
  throw error
}

function useData(actor, path, options = {}) {
  return useQuery({
    queryKey: ['account', actor.id, path],
    queryFn: ({ signal }) => request(path, { account: actor.id, signal }),
    ...options,
  })
}

function useChange(actor) {
  const cache = useQueryClient()
  return useMutation({
    mutationFn: ({ path, method, data }) => request(path, { method, data, account: actor.id }),
    onSettled: () => cache.invalidateQueries({ queryKey: ['account', actor.id] }),
  })
}

function Failure({ error }) {
  return error ? <p className="error" role="alert">{error.message}</p> : null
}

function Status({ state }) {
  return <span className="status">{states[state] || state.replaceAll('_', ' ')}</span>
}

function OpportunityForm({ change, close }) {
  const [description, setDescription] = useState('')
  const [fileError, setFileError] = useState(null)

  async function readDescription(event) {
    const file = event.target.files[0]
    if (!file) return
    setFileError(null)
    if (file.size > 48000) {
      setFileError(new Error('Choose a text file under 48 KB.'))
      return
    }
    try {
      const content = await file.text()
      if (content.length > 12000) throw new Error('The description can contain up to 12,000 characters.')
      setDescription(content)
    } catch (error) {
      setFileError(error)
    }
  }

  function submit(event) {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    const enteredSkills = form.get('criteria').split(',').map(value => value.trim()).filter(Boolean)
    const criteria = Object.fromEntries(enteredSkills.map(pair => {
      const [name, level] = pair.split(':')
      return [name.trim(), Number(level)]
    }))
    const data = {
      title: form.get('title'), project: form.get('project'), needed_by: form.get('needed_by'),
      growth: form.get('growth'), experience: form.get('experience'), description, criteria,
      interview_questions: form.get('interview_questions').split(/\\r?\\n/).map(line => line.trim()).filter(Boolean),
      client_interview_required: form.has('client_interview_required'),
      publish: event.nativeEvent.submitter?.value !== 'draft',
    }
    change.mutate({ path: '/opportunities', method: 'POST', data }, { onSuccess: created => close(created.id) })
  }

  return <form className="panel form" onSubmit={submit}>
    <h2>New opportunity</h2>
    <div className="fields">
      <label>Role title<input name="title" maxLength={100} required /></label>
      <label>Project<input name="project" maxLength={100} required /></label>
      <label>Needed by<input name="needed_by" type="date" required /></label>
      <label>Experience<input name="experience" maxLength={500} /></label>
    </div>
    <label>Upload job description<input type="file" accept=".txt,.md,text/plain,text/markdown" onChange={readDescription} /></label>
    <Failure error={fileError} />
    <label>Job description<textarea value={description} onChange={event => setDescription(event.target.value)} maxLength={12000} /></label>
    <label>Skill criteria<input name="criteria" placeholder="Python:5, APIs:4" aria-describedby="criteria-help" />
      <small id="criteria-help">Use levels from 1 to 5. Leave blank to map recognized skills from the job description.</small>
    </label>
    <label>Growth opportunities<textarea name="growth" maxLength={500} required /></label>
    <label>Assessment questions<textarea name="interview_questions" placeholder="One question per line, up to six." /></label>
    <label className="check-label"><input name="client_interview_required" type="checkbox" /> Client interview required</label>
    <div className="actions">
      <button disabled={change.isPending}>Publish opportunity</button>
      <button className="secondary" value="draft" disabled={change.isPending}>Save draft</button>
      <button type="button" className="secondary" onClick={close}>Cancel</button>
    </div>
  </form>
}

function MatchCard({ match }) {
  return <article className="panel match">
    <div className="row"><div><h3>{match.name}</h3><p>{match.role}</p></div>
      <strong className="score">{match.score === null ? '—' : match.score + '%'}</strong></div>
    <p className="confidence">Evidence confidence · {match.confidence}</p>
    <ul className="evidence">{match.evidence.map(item => <li key={item.skill}>
      <span>{item.skill}<small>{item.source || 'Evidence missing'}</small></span>
      <strong>{item.level ?? '—'} / {item.needed}</strong>
    </li>)}</ul>
  </article>
}

function ResumeMatchNotice({ status }) {
  if (status === 'ready') return null
  return <p>
    {status === 'unreadable'
      ? 'We could not read text from your resume. Upload a DOCX or a PDF with selectable text to get match scores.'
      : 'Upload your resume to score these opportunities against your experience.'}{' '}
    <Link to="/applications#resume">Go to your resume</Link>
  </p>
}

function OpportunityRecommendations({ query, selected, onSelect }) {
  const results = query.data
  return <section className="panel ranked-opportunities" aria-labelledby="recommended-title">
    <h2 id="recommended-title">Recommended opportunities</h2>
    <Failure error={query.error} />
    {query.isPending && <p role="status">Comparing your resume with published openings…</p>}
    {results && <>
      <ResumeMatchNotice status={results.resume_status} />
      {results.opportunities.length === 0 && <p>No published opportunities yet.</p>}
      <ol className="ranked-list">
        {results.opportunities.map((item, index) => <li key={item.id}>
          <button type="button" className="secondary ranked-item" aria-pressed={selected === item.id}
            onClick={() => onSelect(item.id)}>
            <span>
              {index === 0 && item.score > 0 && <small className="top-match">Best match</small>}
              <strong>{item.title}</strong>
              <small>{item.project}</small>
              {item.score != null && <small>{item.matched_count} of {item.requirements_count} skills evidenced</small>}
              {item.gaps.length > 0 && <small>Gap: {item.gaps.join(', ')}</small>}
            </span>
            {item.score != null && <span className="score">{item.score}%</span>}
          </button>
        </li>)}
      </ol>
    </>}
  </section>
}

function LearningRequestForm({ actor, role, ticket }) {
  const path = '/opportunities/' + encodeURIComponent(role.id)
  const draft = useMutation({ mutationFn: () => request(path + '/learning-request-draft', { account: actor.id }) })
  const submit = useChange(actor)
  const received = ticket || submit.data

  if (received) return <p className="learning-ticket-status" role="status">
    <strong>{received.acknowledged_at ? 'Acknowledged by L&D' : 'Submitted to L&D'}</strong>{' '}
    <span className="ticket-id">#{received.id.slice(0, 8).toUpperCase()}</span>
  </p>

  return <>
    <Failure error={draft.error || submit.error} />
    {draft.data ? <form className="form learning-draft" onSubmit={event => {
      event.preventDefault()
      const fields = new FormData(event.currentTarget)
      submit.mutate({ path: path + '/learning-requests', method: 'POST', data: {
        subject: fields.get('subject'), message: fields.get('message'), approved: true,
        resume_updated_at: draft.data.resume_updated_at,
      } })
    }}>
      <h4>Review your L&D request</h4>
      <label>Subject<input name="subject" defaultValue={draft.data.subject} minLength={3} maxLength={180} required /></label>
      <label>Request message<textarea name="message" defaultValue={draft.data.message} minLength={10} maxLength={4000} rows={9} required /></label>
      <div className="actions">
        <button disabled={submit.isPending}>{submit.isPending ? 'Sending…' : 'Approve and send to L&D'}</button>
        <button type="button" className="secondary" disabled={submit.isPending} onClick={() => { draft.reset(); submit.reset() }}>Cancel</button>
      </div>
    </form> : <button className="secondary" disabled={draft.isPending} onClick={() => draft.mutate()}>
      {draft.isPending ? 'Preparing request…' : 'Raise request'}
    </button>}
  </>
}

function ResumeMatch({ match, actor, role }) {
  return <section className="panel list">
    <div className="row">
      <h2>Your resume match</h2>
      {match.score != null && <strong className="score">{match.score}%</strong>}
    </div>
    <ResumeMatchNotice status={match.resume_status} />
    {match.score != null && <>
      <p>{match.matched_count} of {match.requirements.length} required skills appear in your resume.</p>
      <ul className="evidence">
        {match.requirements.map(item => <li key={item.skill}>
          <strong>{item.skill}</strong>
          <span className={item.matched ? 'status' : 'status status-due'}>{item.matched ? 'In resume' : 'Gap'}</span>
        </li>)}
      </ul>
      {match.gaps.length > 0 && <div>
        <h3>Steps to close the gaps</h3>
        {match.gaps.map(gap => <div className="learning-gap" key={gap.skill}>
          <h4>{gap.skill}</h4><ol>{gap.steps.map(step => <li key={step}>{step}</li>)}</ol>
        </div>)}
        <p className="learning-help">Raise a request if you need L&D to help with training, a sandbox, or mentoring.</p>
      </div>}
    </>}
    {(match.ticket || match.gaps.length > 0) && <LearningRequestForm actor={actor} role={role} ticket={match.ticket} />}
  </section>
}

function OpportunityDetail({ actor, role, profile, change, application }) {
  const matches = useData(actor, '/opportunities/' + role.id + '/matches', { enabled: actor.engagement_side === 'receiving' })
  const [goal, setGoal] = useState(profile?.goal ?? '')
  const employee = Boolean(profile?.employee)
  const myMatch = useData(actor, '/opportunities/' + role.id + '/my-match', { enabled: employee })

  return <>
    <div className="panel role-detail">
      <p className="project">{role.project}</p>
      <h2>{role.title}</h2>
      <p>{role.growth}</p><p><strong>Needed by:</strong> {role.needed_by}</p>
      {role.experience && <p><strong>Experience:</strong> {role.experience}</p>}
      {role.description && <details><summary>Job description</summary><p className="preserved-text">{role.description}</p></details>}
      {role.client_interview_required && <p><strong>Selection includes a client interview.</strong></p>}
      {role.status === 'draft' && <div className="actions">
        <Status state="draft" />
        <button disabled={change.isPending} onClick={() => change.mutate({
          path: '/opportunities/' + role.id + '/publish', method: 'POST',
        })}>Publish opportunity</button>
      </div>}
      <div className="tags">{Object.entries(role.criteria).map(([skill, level]) =>
        <span key={skill}>{skill} · {level}/5</span>)}</div>
    </div>
    {actor.engagement_side === 'receiving' && <><h2 className="section-heading">Internal shortlist</h2>
      <Failure error={matches.error} />
      {matches.isPending && <p role="status">Loading shortlist…</p>}
      <div className="grid">{matches.data?.map(match => <MatchCard match={match} key={match.employee} />)}</div>
    </>}
    {employee && <div className="list opportunity-personal">
      <section className="list">
        <Failure error={myMatch.error} />
        {myMatch.isPending && <p role="status">Analyzing your resume match…</p>}
        {myMatch.data && <ResumeMatch match={myMatch.data} actor={actor} role={role} />}
      </section>
      <section className="panel form">
      <h2>Career alignment</h2>
      <form onSubmit={event => {
        event.preventDefault()
        change.mutate({ path: '/me/aspirations', method: 'PATCH', data: { goal } })
      }}>
        <label>What do you want to develop?<textarea value={goal} onChange={event => setGoal(event.target.value)} minLength={2} maxLength={500} required /></label>
        <button className="secondary" disabled={change.isPending || goal === profile.goal}>Save career goal</button>
      </form>
      {application && application.state !== 'declined'
        ? <Link className="button" to={'/applications/' + application.id}>Open transition</Link>
        : <div className="actions">
          {[true, false].map(interested => <button key={String(interested)}
            className={interested ? '' : 'secondary'}
            disabled={change.isPending || (interested && (!profile.goal || goal !== profile.goal)) || (!interested && application?.state === 'declined')}
            onClick={() => change.mutate({ path: '/opportunities/' + role.id + '/applications', method: 'POST', data: { interested } })}>
            {interested ? 'Apply for opportunity' : (application ? 'Declined' : 'Decline')}
          </button>)}
        </div>}
      </section>
    </div>}
  </>
}

function Opportunities({ actor }) {
  const opportunities = useData(actor, '/opportunities')
  const recommendations = useData(actor, '/opportunities/recommendations', { enabled: actor.employee })
  const profile = useData(actor, '/me')
  const applications = useData(actor, '/applications')
  const change = useChange(actor)
  const [params, setParams] = useSearchParams()
  const selected = params.get('opportunity')
  const select = id => setParams({ opportunity: id }, { replace: true })
  const [creating, setCreating] = useState(false)
  const best = actor.employee ? recommendations.data?.opportunities[0]?.id : undefined
  const role = opportunities.data?.find(item => item.id === (selected || best)) ?? opportunities.data?.[0]

  return <>
    <header className="hero"><div><h1>Opportunities</h1><p>Find internal talent and prepare for project transitions.</p></div>
      {actor.engagement_side === 'receiving' && <button onClick={() => setCreating(true)}>New opportunity</button>}
    </header>
    <Failure error={opportunities.error || profile.error || applications.error || change.error} />
    {creating && <OpportunityForm change={change} close={id => { if (typeof id === 'string') select(id); setCreating(false) }} />}
    {opportunities.isPending && <p role="status">Loading opportunities…</p>}
    {actor.employee && <div className="opportunity-layout">
      <OpportunityRecommendations query={recommendations} selected={role?.id} onSelect={select} />
      <div>
        {role && profile.data && <OpportunityDetail key={role.id} actor={actor} role={role} profile={profile.data}
          change={change} application={applications.data?.find(item => item.opportunity_id === role.id)} />}
      </div>
    </div>}
    {!actor.employee && role && profile.data && <>
      <label className="picker">Opportunity<select value={role.id} onChange={event => select(event.target.value)}>
        {opportunities.data.map(item => <option key={item.id} value={item.id}>{item.project} · {item.title}{item.status === 'draft' ? ' (Draft)' : ''}</option>)}
      </select></label>
      <OpportunityDetail key={role.id} actor={actor} role={role} profile={profile.data}
        change={change} application={applications.data?.find(item => item.opportunity_id === role.id)} />
    </>}
  </>
}

function useApplications(actor) {
  return useData(actor, '/applications', {
    refetchInterval: query => query.state.data?.some(item => ['drafting', 'assessing'].includes(item.state)) ? 850 : false,
  })
}

function CareerDate({ value }) {
  const date = new Date(value + 'T00:00:00Z')
  return <time dateTime={value}>{date.toLocaleDateString(undefined, {
    year: 'numeric', month: 'short', day: 'numeric', timeZone: 'UTC',
  })}</time>
}

function resumeDueLabel(days) {
  if (days < 0) return 'Overdue'
  if (days === 0) return 'Due today'
  if (days <= 14) return 'Due in ' + days + (days === 1 ? ' day' : ' days')
  return 'Up to date'
}

function ResumePanel({ actor }) {
  const cache = useQueryClient()
  const resume = useData(actor, '/me/resume')
  const [fileError, setFileError] = useState(null)
  const [notice, setNotice] = useState('')
  const upload = useMutation({
    gcTime: 0,
    mutationFn: file => request('/me/resume?' + new URLSearchParams({ filename: file.name }), {
      method: 'PUT', file, account: actor.id,
    }),
    onSuccess: data => {
      cache.setQueryData(['account', actor.id, '/me/resume'], data)
      void cache.invalidateQueries({ queryKey: ['account', actor.id] })
    },
  })
  const download = useMutation({
    gcTime: 0,
    mutationFn: () => request('/me/resume/download', { account: actor.id, download: true }),
  })
  const current = resume.data

  function submit(event) {
    event.preventDefault()
    const form = event.currentTarget
    const file = new FormData(form).get('resume')
    setFileError(null)
    setNotice('')
    if (!file?.size || file.size > current.max_bytes) {
      setFileError(new Error('Choose a PDF or DOCX file between 1 byte and 5 MB.'))
      return
    }
    upload.mutate(file, { onSuccess: () => {
      form.reset()
      upload.reset()
      setNotice('Resume updated.')
    } })
  }

  function downloadCurrent() {
    download.mutate(undefined, { onSuccess: file => {
      const url = URL.createObjectURL(file)
      const link = document.createElement('a')
      link.href = url
      link.download = current.filename
      link.click()
      window.setTimeout(() => URL.revokeObjectURL(url), 30000)
      download.reset()
    } })
  }

  return <section id="resume" className="panel resume-panel" aria-labelledby="resume-title">
    <div className="row"><h2 id="resume-title">Resume</h2>
      {current && <span className={current.days_until_due <= 14 ? 'status status-due' : 'status'}>{resumeDueLabel(current.days_until_due)}</span>}
    </div>
    <Failure error={resume.error || fileError || upload.error || download.error} />
    {resume.isPending && <p role="status">Loading resume status…</p>}
    {current && <>
      <p>Update your resume every {current.interval_days} days.</p>
      <dl className="career-facts">
        <div><dt>Last updated</dt><dd>{current.updated_at ? <CareerDate value={current.updated_at.slice(0, 10)} /> : 'No resume uploaded'}</dd></div>
        <div><dt>{current.updated_at ? 'Next update due' : 'First update due'}</dt><dd><CareerDate value={current.due_on} /></dd></div>
      </dl>
      <form className="form resume-form" onSubmit={submit}>
        <label>Resume file<input name="resume" type="file" accept=".pdf,.docx" required disabled={upload.isPending} />
          <small>PDF or DOCX, up to 5 MB.</small>
        </label>
        <div className="actions">
          <button disabled={upload.isPending || download.isPending}>{upload.isPending ? 'Uploading…' : current.filename ? 'Update resume' : 'Upload resume'}</button>
          {current.filename && <button type="button" className="secondary" disabled={download.isPending || upload.isPending}
            onClick={downloadCurrent}>Download {current.filename}</button>}
        </div>
      </form>
      {notice && <p role="status">{notice}</p>}
    </>}
  </section>
}

function CareerHistory({ profile }) {
  const milestones = [
    { id: 'joined', on: profile.joined_on, title: 'Joined the organization', summary: profile.entry_role },
    ...profile.role_changes.map(change => ({
      id: 'role-' + change.on, on: change.on, title: change.role, summary: change.summary,
    })),
    ...profile.projects.flatMap(project => {
      const start = { id: project.id + '-start', on: project.started_on, title: 'Started ' + project.name, summary: project.role }
      return project.ended_on
        ? [start, { id: project.id + '-end', on: project.ended_on, title: 'Completed ' + project.name, summary: project.role }]
        : [start]
    }),
  ].sort((a, b) => b.on.localeCompare(a.on))

  return <section className="career-history list" aria-labelledby="career-heading">
    <section className="panel career-overview">
      <div><h2 id="career-heading">Career history</h2><p>{profile.name}</p></div>
      <dl className="career-facts">
        <div><dt>Joined</dt><dd><CareerDate value={profile.joined_on} /></dd></div>
        <div><dt>Employee role</dt><dd>{profile.role}</dd></div>
      </dl>
    </section>
    <div className="detail-layout">
      <section className="panel">
        <h3>Projects & technologies</h3>
        {profile.projects.length === 0 && <p>No projects recorded.</p>}
        <ul className="career-projects">
          {profile.projects.map(project => <li key={project.id}>
            <div className="row">
              <div><h4>{project.name}</h4><p>{project.role}</p></div>
              <Status state={project.ended_on ? 'completed' : 'active'} />
            </div>
            <p><small><CareerDate value={project.started_on} /> – {project.ended_on
              ? <CareerDate value={project.ended_on} /> : 'Present'}</small></p>
            {project.summary && <p>{project.summary}</p>}
            {(project.technologies || project.role_skills).length > 0 && <>
              <div className="tags" aria-label={project.technologies ? 'Technologies used' : 'Role skills'}>
                {(project.technologies || project.role_skills).map(skill => <span key={skill}>{skill}</span>)}
              </div>
              {project.role_skills && <p className="career-source"><small>Skills listed on the opportunity</small></p>}
            </>}
            {project.transition_id && <>
              <Link to={'/applications/' + encodeURIComponent(project.transition_id)}>View project transition</Link>
            </>}
          </li>)}
        </ul>
      </section>
      <section className="panel history">
        <h3>Career timeline</h3>
        <ol className="career-timeline">
          {milestones.map(item => <li key={item.id}>
            <small><CareerDate value={item.on} /></small>
            <strong>{item.title}</strong>
            <p>{item.summary}</p>
          </li>)}
        </ol>
      </section>
    </div>
  </section>
}

function Transitions({ actor, workspace }) {
  const records = useApplications(actor)
  const career = useData(actor, '/me/career-history', { enabled: actor.employee })
  return <>
    <header className="hero"><div><h1>{workspace.transitions}</h1><p>{workspace.description}</p></div></header>
    {actor.employee && <>
      <ResumePanel actor={actor} />
      <Failure error={career.error} />
      {career.isPending && <p role="status">Loading career history…</p>}
      {career.data && <CareerHistory profile={career.data} />}
      <h2 className="section-heading">Transition applications</h2>
    </>}
    <Failure error={records.error} />
    {records.isPending && <p role="status">Loading transitions…</p>}
    {records.data?.length === 0 && <p className="panel">{actor.employee ? 'You have no transition applications yet.' : 'No transitions are available for this account.'}</p>}
    <div className="list">{records.data?.map(item => <Link className="panel transition-link" key={item.id} to={'/applications/' + encodeURIComponent(item.id)}>
      <div>
        <strong>{actor.employee ? item.project || item.opportunity_title || 'Project transition' : item.name}</strong>
        <p>{item.opportunity_title || item.match.role}</p>
      </div>
      <Status state={item.state} />
    </Link>)}</div>
  </>
}

function TransitionActions({ item, change }) {
  const action = item.allowed_actions.includes('decide') ? 'decide' : item.allowed_actions[0]
  const path = '/applications/' + item.id
  function send(suffix, data = {}, method = 'POST') {
    change.mutate({ path: path + suffix, method, data: { revision: item.revision, ...data } })
  }

  if (!action) return null
  if (action === 'draft_plan') return <button disabled={change.isPending} onClick={() => send('/plan-drafts')}>Draft preparation plan</button>
  if (action === 'provision_access') return <button disabled={change.isPending} onClick={() => send('/allocation')}>Confirm project access and open onboarding</button>
  if (action === 'complete_task' || action === 'assess_readiness') return null
  if (action === 'schedule_interview') return <form className="form" onSubmit={event => {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    send('/interview-schedule', { scheduled_at: new Date(form.get('scheduled_at')).toISOString(), details: form.get('details') })
  }}>
    <label>Interview date and time<input type="datetime-local" name="scheduled_at" required /></label>
    <label>Meeting details<textarea name="details" minLength={2} maxLength={500} required /></label>
    <button disabled={change.isPending}>Schedule {item.state === 'fitment' ? 'fit discussion' : 'client interview'}</button>
  </form>
  if (action === 'submit_attempt') return <form className="form" onSubmit={event => {
    event.preventDefault()
    send('/attempts', { answers: new FormData(event.currentTarget).getAll('answer') })
  }}>
    {(item.interview_questions || [item.scenario || 'Describe your approach to the project scenario.']).map((question, index) =>
      <label key={index}>{question}
        <textarea name="answer" minLength={12} maxLength={4000} required
          defaultValue={item.failed_answers?.[index] || (index === 0 ? item.failed_answer : '')} />
      </label>)}
    <button disabled={change.isPending}>Submit interview responses</button>
  </form>
  if (action === 'resume') return <button disabled={change.isPending} onClick={() => send('/resume')}>Reopen review</button>

  const forms = {
    confirm_plan: { label: 'How does this opportunity support your goal?', field: 'alignment', endpoint: '/plan', method: 'PATCH', button: 'Confirm plan', min: 2 },
    decide: { label: 'Decision reason', field: 'reason', endpoint: '/decisions', method: 'POST', button: 'Approve', min: 2 },
  }
  const form = forms[action]
  if (!form) return null
  const approveLabel = { sme_review: 'Confirm readiness', fitment: 'Confirm fit', client_interview: 'Record client approval',
    activation_review: 'Approve and activate' }[item.state] || form.button
  const holdLabel = { sme_review: 'Request more preparation', fitment: 'Record not selected', client_interview: 'Record not selected',
    activation_review: 'Return for reassessment' }[item.state] || 'Place on hold'
  return <form className="form" onSubmit={event => {
    event.preventDefault()
    const value = new FormData(event.currentTarget).get(form.field)
    const data = { [form.field]: value }
    if (action === 'decide') data.approved = event.nativeEvent.submitter?.value !== 'hold'
    send(form.endpoint, data, form.method)
  }}>
    <label>{form.label}<textarea name={form.field} minLength={form.min} maxLength={500} required /></label>
    <div className="actions"><button disabled={change.isPending}>{approveLabel}</button>
      {action === 'decide' && <button className="secondary" value="hold" disabled={change.isPending}>
        {holdLabel}
      </button>}</div>
  </form>
}

function KnowledgeResources({ resources }) {
  return <div>{resources.map(resource => <details key={resource.id}>
    <summary>{resource.title}</summary><p>{resource.text}</p><small>{resource.id}</small>
  </details>)}</div>
}

function Onboarding({ item, actor, change }) {
  const { onboarding } = item
  const canAssess = item.allowed_actions.includes('assess_readiness')
  const assessment = useData(actor, '/readiness-check', { enabled: canAssess })
  const submit = (action, data) => change.mutate({ path: '/applications/' + item.id + '/' + action,
    method: 'POST', data: { ...data, revision: item.revision } })
  return <section className="panel list">
    <div><h2>Onboarding and readiness</h2><p>Project access confirmed {new Date(onboarding.access_at).toLocaleString()}.</p></div>
    <div><h3>Knowledge transfer hub</h3><KnowledgeResources resources={onboarding.sources} /></div>
    <div><h3>Onboarding checklist</h3>
      <ul className="checklist">{Object.entries(onboarding.checks).map(([id, label]) => {
        const done = onboarding.completed.includes(id)
        return <li key={id}><span>{label}</span>
          {item.allowed_actions.includes('complete_task') && !done
            ? <button className="secondary" disabled={change.isPending} onClick={() => submit('onboarding-tasks', { task: id })}>Mark complete</button>
            : <Status state={done ? 'complete' : 'pending'} />}
        </li>
      })}</ul>
    </div>
    {item.trs && <div>
      <h3>Transition Readiness Score</h3>
      <p><strong className="score">{item.trs.score}%</strong> · {item.trs.threshold}% required for final review</p>
      <ul>{item.trs.results.map((result, index) => <li key={index}>Question {index + 1} · {result.correct ? 'Correct' : 'Review material'} · {result.source}</li>)}</ul>
    </div>}
    {item.readiness_return_reason && <p><strong>Reassessment requested:</strong> {item.readiness_return_reason}</p>}
    {canAssess && <>
      <Failure error={assessment.error} />
      {assessment.isPending && <p role="status">Loading readiness check…</p>}
      {assessment.data && <form className="form" onSubmit={event => {
        event.preventDefault()
        const form = new FormData(event.currentTarget)
        const responses = assessment.data.questions.map((_, index) => Number(form.get('question-' + index)))
        submit('readiness-assessments', { responses })
      }}>
        <h3>Readiness assessment</h3>
        {assessment.data.questions.map((question, index) => <label key={question.prompt}>{question.prompt}
          <select name={'question-' + index} defaultValue="" required>
            <option value="" disabled>Choose a response</option>
            {question.options.map((option, value) => <option key={option} value={value}>{option}</option>)}
          </select>
        </label>)}
        <button disabled={change.isPending}>Submit readiness assessment</button>
      </form>}
    </>}
    <TransitionActions key={item.state} item={item} change={change} />
    {item.allocation && <p><strong>Activated on project:</strong> {new Date(item.allocation.at).toLocaleString()}</p>}
  </section>
}

function Transition({ actor, workspace }) {
  const { id } = useParams()
  const records = useApplications(actor)
  const change = useChange(actor)
  const item = records.data?.find(record => record.id === id)
  if (!item) return <><Failure error={records.error} /><p role="status">{records.isPending ? 'Loading transition…' : 'Transition unavailable for this account.'}</p></>

  return <>
    <Link className="back" to="/applications">← {workspace.transitions}</Link>
    <header className="hero"><div><h1>{item.name}</h1><p>{item.match.role}</p></div><Status state={item.state} /></header>
    <Failure error={change.error} />
    <div className="detail-layout">
      <div className="list">
        <section className="panel"><h2>Career alignment</h2><p>{item.goal || 'No goal recorded.'}</p>
          {item.alignment && <p><strong>Employee reflection:</strong> {item.alignment}</p>}
        </section>
        <section className="panel list"><div><h2>Preparation and assessment</h2><Status state={item.readiness} /></div>
          {item.preparation_due && <p><strong>Preparation target:</strong> {new Date(item.preparation_due).toLocaleString()} (48 hours from application)</p>}
          {item.plan && <div>
            {item.preparation?.role_title && <p><strong>{item.preparation.role_title}</strong> · {item.preparation.project}. {item.preparation.growth}</p>}
            {item.preparation?.topics?.length > 0 && <p><strong>Key topics:</strong> {item.preparation.topics.join(', ')}</p>}
            {item.preparation?.learning?.length > 0 && <p><strong>Suggested learning:</strong> {item.preparation.learning.map(entry => entry.title).join(', ')}</p>}
            <p><strong>Mock scenario:</strong> {item.scenario}</p>
            <KnowledgeResources resources={item.sources} />
          </div>}
          {item.attempts.map((attempt, index) => <details key={attempt.at} open={index === item.attempts.length - 1}>
            <summary>Interview attempt {index + 1}{attempt.score != null && ' · ' + attempt.score + '% rubric coverage'}</summary>
            {attempt.responses ? attempt.responses.map((response, i) => <div key={i}>
              <p><strong>{response.question}</strong></p><p>{response.answer}</p>
            </div>) : <p>{attempt.answer}</p>}
            <ul>{attempt.feedback.map(line => <li key={line.criterion}>{line.criterion} · {line.covered ? 'Covered' : 'Needs practice'} · {line.source}</li>)}</ul>
          </details>)}
          {['drafting', 'assessing'].includes(item.state) && <p role="status">Processing. This page updates automatically.</p>}
        </section>
        {(item.interviews || ['fitment', 'client_interview'].includes(item.state)) && <section className="panel list">
          <h2>Selection interviews</h2>
          {Object.entries(item.interviews || {}).map(([phase, interview]) => <div key={phase}>
            <h3>{phase === 'fitment' ? 'Senior fit discussion' : 'Client interview'}</h3>
            <p>{new Date(interview.at).toLocaleString()} · {interview.details}</p>
            {interview.reason && <p>{interview.passed ? 'Passed' : 'Not selected'} · {interview.reason}</p>}
          </div>)}
          {item.state === 'client_interview' && <div>
            <h3>Client interview preparation</h3>
            <p>Review the project context and practice explaining your approach, the client impact, and your next update.</p>
            <KnowledgeResources resources={item.sources || []} />
          </div>}
        </section>}
        {!item.onboarding && item.allowed_actions.length > 0 && <section className="panel">
          <h2>Next action</h2><TransitionActions key={item.state} item={item} change={change} />
        </section>}
        {item.onboarding && <Onboarding item={item} actor={actor} change={change} />}
        {item.allocation && !item.onboarding && <section className="panel"><h2>Onboarding blueprint</h2><ul>
          {item.allocation.onboarding.map(task => <li key={task}>{task}</li>)}</ul>
        </section>}
      </div>
      <aside className="panel history"><h2>Transition history</h2><ol>
        {[...item.history].reverse().map((event, index) => <li key={event.at + index}>
          <strong>{states[event.state]}</strong>
          <p>{event.reason}</p><small>{event.by} · {new Date(event.at).toLocaleString()}</small>
        </li>)}
      </ol></aside>
    </div>
  </>
}

function Support({ actor }) {
  const overview = useData(actor, '/support')
  const resume = useData(actor, '/me/resume', { enabled: actor.employee })
  const ask = useMutation({ mutationFn: question => request('/support/ask', {
    account: actor.id, method: 'POST', data: { question },
  }) })
  return <>
    <header className="hero"><div><h1>Updates & support</h1><p>Follow transition updates and find project guidance.</p></div></header>
    {resume.data?.days_until_due <= 14 && <section className="panel resume-panel">
      <h2>Resume update</h2>
      <p>{resumeDueLabel(resume.data.days_until_due)} · Due <CareerDate value={resume.data.due_on} /></p>
      <Link to="/applications#resume" onClick={() => {
        requestAnimationFrame(() => document.getElementById('resume')?.scrollIntoView())
      }}>Update your resume</Link>
    </section>}
    <Failure error={overview.error} />
    {overview.isPending && <p role="status">Loading updates…</p>}
    <div className="detail-layout">
      <div className="list">
        {actor.employee && <section className="panel"><h2>Opportunity notifications</h2>
          {overview.data?.openings.length === 0 && <p>No published opportunities.</p>}
          <ul className="support-list">{overview.data?.openings.map(opening => <li key={opening.id}>
            <Link to={'/?opportunity=' + encodeURIComponent(opening.id)}>{opening.title} · {opening.project}</Link>
            {opening.at && <small>{new Date(opening.at).toLocaleString()}</small>}
          </li>)}</ul>
        </section>}
        {actor.engagement_side === 'receiving' && <section className="panel"><h2>Learning support requests</h2>
          {overview.data?.learning_requests.length === 0 && <p>No learning support requests.</p>}
          <ul className="support-list">{overview.data?.learning_requests.map(item => <li key={item.id}>
            <Link to={'/?opportunity=' + encodeURIComponent(item.opportunity_id)}>{item.name} · {item.title}</Link>
            <small>{item.project} · {new Date(item.at).toLocaleString()}</small>
          </li>)}</ul>
        </section>}
        <section className="panel"><h2>Transition updates</h2>
          {overview.data?.updates.length === 0 && <p>No transition updates yet.</p>}
          <ul className="support-list">{overview.data?.updates.map(update => <li key={update.id}>
            <Link to={'/applications/' + update.id}>{update.name} · {states[update.state] || update.state}</Link>
            <small>{update.reason} · {new Date(update.at).toLocaleString()}</small>
          </li>)}</ul>
        </section>
        <section className="panel"><h2>Knowledge hub</h2>
          <KnowledgeResources resources={overview.data?.knowledge || []} />
        </section>
      </div>
      <aside className="list">
        <section className="panel"><h2>Transition status</h2>
          {overview.data && Object.keys(overview.data.counts).length === 0 && <p>No transitions to report.</p>}
          <ul className="support-list">{Object.entries(overview.data?.counts || {}).map(([state, count]) =>
            <li className="row" key={state}><span>{states[state] || state}</span><strong>{count}</strong></li>
          )}</ul>
        </section>
        <section className="panel">
          <h2>Ask Transition IQ</h2>
          <form className="form" onSubmit={event => {
            event.preventDefault()
            ask.mutate(new FormData(event.currentTarget).get('question'))
          }}>
            <label>Your question<input name="question" placeholder="How do I complete onboarding?" minLength={2} maxLength={300} required /></label>
            <button disabled={ask.isPending}>Find guidance</button>
          </form>
          <Failure error={ask.error} />
          {ask.data && <div aria-live="polite"><p>{ask.data.answer}</p>
            {ask.data.sources.map(entry => <small key={entry.id}>{entry.id} · {entry.title}<br /></small>)}
          </div>}
        </section>
      </aside>
    </div>
  </>
}

function LearningDashboard({ actor }) {
  const queue = useData(actor, '/learning-tickets', { refetchInterval: 15000 })
  const change = useChange(actor)
  return <>
    <header className="hero">
      <div><h1>L&D Requests</h1><p>Review training and mentoring requests approved by employees.</p></div>
      {queue.data && <span className={queue.data.new_count ? 'status status-due' : 'status'} role="status">
        {queue.data.new_count} new {queue.data.new_count === 1 ? 'request' : 'requests'}
      </span>}
    </header>
    <Failure error={queue.error || change.error} />
    {queue.isPending && <p role="status">Loading learning requests…</p>}
    {queue.data?.tickets.length === 0 && <p className="panel">No learning requests have been submitted.</p>}
    <div className="list">
      {queue.data?.tickets.map(ticket => <article className="panel list" key={ticket.id}>
        <div className="row">
          <div>
            <h2>{ticket.subject}</h2>
            <p>{ticket.employee} · {ticket.project} · {ticket.title}</p>
          </div>
          <span className={ticket.acknowledged_at ? 'status' : 'status status-due'}>{ticket.acknowledged_at ? 'Acknowledged' : 'New'}</span>
        </div>
        <p><small>#{ticket.id.slice(0, 8).toUpperCase()} · {new Date(ticket.created_at).toLocaleString()}</small></p>
        <div className="tags">{ticket.skills.map(skill => <span key={skill}>{skill}</span>)}</div>
        <details><summary>Read approved request</summary><p className="preserved-text">{ticket.message}</p></details>
        {!ticket.acknowledged_at && <div><button className="secondary" disabled={change.isPending} onClick={() =>
          change.mutate({ path: '/learning-tickets/' + ticket.id + '/acknowledge', method: 'POST' })}>Acknowledge request</button></div>}
      </article>)}
    </div>
  </>
}

function Login({ onLogin }) {
  const [error, setError] = useState(null)
  const [pending, setPending] = useState(false)

  async function submit(event) {
    event.preventDefault()
    const credentials = Object.fromEntries(new FormData(event.currentTarget))
    setError(null)
    setPending(true)
    try {
      onLogin(await request('/auth/login', { method: 'POST', data: credentials }))
    } catch (failure) {
      setError(failure)
      setPending(false)
    }
  }

  return <main className="sign-in">
    <form className="panel form sign-in-card" onSubmit={submit}>
      <h1>Sign in</h1>
      <p>Access your Transition IQ workspace.</p>
      <Failure error={error} />
      <label>Username<input name="username" autoComplete="username" autoCapitalize="none" maxLength={64} required /></label>
      <label>Password<input name="password" type="password" autoComplete="current-password" maxLength={128} required /></label>
      <button disabled={pending}>{pending ? 'Signing in…' : 'Sign in'}</button>
    </form>
  </main>
}

function App() {
  const cache = useQueryClient()
  const location = useLocation()
  const { data: actor, isPending, error, refetch } = useQuery({
    queryKey: sessionKey,
    queryFn: async ({ signal }) => {
      try {
        return await request('/me', { signal })
      } catch (failure) {
        if (failure.status === 401) return null
        throw failure
      }
    },
  })

  function setSession(profile) {
    void cache.cancelQueries({ queryKey: sessionKey })
    cache.removeQueries({ queryKey: ['account'] })
    cache.setQueryData(sessionKey, profile)
  }

  const logout = useMutation({
    mutationFn: () => request('/auth/logout', { method: 'POST' }),
    onSuccess: () => setSession(null),
  })

  const accountLabel = actor && (engagementLabels[actor.engagement_side] || roleLabels[actor.role])
  const workspace = actor && workspaces[actor.engagement_side || actor.role]
  const home = workspace?.learning ? '/learning' : workspace?.opportunities ? '/' : '/applications'
  let content
  if (isPending) {
    content = <main><p role="status">Checking your session…</p></main>
  } else if (actor === undefined && error) {
    content = <main><Failure error={error} /><button onClick={() => refetch()}>Retry</button></main>
  } else if (!actor) {
    content = location.pathname === '/login'
      ? <Login onLogin={setSession} />
      : <Navigate to="/login" replace state={{ returnTo: location.pathname + location.search + location.hash }} />
  } else {
    content = <main key={actor.id}>
      <Failure error={logout.error} />
      <Routes>
        <Route path="/login" element={<Navigate to={location.state?.returnTo || home} replace />} />
        <Route path="/" element={workspace.opportunities ? <Opportunities actor={actor} /> : <Navigate to={home} replace />} />
        <Route path="/applications" element={workspace.learning ? <Navigate to={home} replace /> : <Transitions actor={actor} workspace={workspace} />} />
        <Route path="/support" element={workspace.learning ? <Navigate to={home} replace /> : <Support actor={actor} />} />
        <Route path="/applications/:id" element={workspace.learning ? <Navigate to={home} replace /> : <Transition actor={actor} workspace={workspace} />} />
        <Route path="/learning" element={workspace.learning ? <LearningDashboard actor={actor} /> : <Navigate to={home} replace />} />
        <Route path="*" element={<p>Page unavailable. <Link to={home}>Back to workspace</Link></p>} />
      </Routes>
    </main>
  }

  return <>
    <header className="top"><div className="top-inner">
      <Link className="brand" to={actor ? home : '/login'}><span className="brand-mark" aria-hidden="true">↗</span>Transition IQ</Link>
      {actor && <>
        <nav aria-label="Main navigation">
          {workspace.learning ? <NavLink to="/learning">L&D Requests</NavLink> : <>
            {workspace.opportunities && <NavLink to="/" end>Opportunities</NavLink>}
            <NavLink to="/applications">{workspace.transitions}</NavLink>
            <NavLink to="/support">Updates & support</NavLink>
          </>}
        </nav>
        <div className="actor">
          <div><strong>{actor.name}</strong>{actor.name !== accountLabel && <span>{accountLabel}</span>}</div>
          <button className="secondary" disabled={logout.isPending} onClick={() => logout.mutate()}>Sign out</button>
        </div>
      </>}
    </div></header>
    {content}
  </>
}

createRoot(document.getElementById('root')).render(
  <QueryClientProvider client={client}><BrowserRouter><App /></BrowserRouter></QueryClientProvider>,
)
