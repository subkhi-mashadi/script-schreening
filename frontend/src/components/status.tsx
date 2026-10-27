import {
  COMPLIANCE_LABELS,
  DECISION_LABELS,
  EDITORIAL_LABELS,
  ISBN_LABELS,
  OBSERVED_LABELS,
  RUN_STATUS_LABELS,
  SEVERITY_LABELS,
  VERIFY_LABELS,
} from '../labels'
import type { IconName } from './icons'
import { Pill, type Tone } from './ui'

type Spec = { tone: Tone; icon: IconName }

const ISBN: Record<string, Spec> = {
  PASS: { tone: 'ok', icon: 'checkCircle' },
  FAIL: { tone: 'bad', icon: 'xCircle' },
  NEEDS_VERIFICATION: { tone: 'warn', icon: 'shield' },
  NOT_APPLICABLE: { tone: 'neutral', icon: 'info' },
  INCOMPLETE: { tone: 'neutral', icon: 'clock' },
}

const EDITORIAL: Record<string, Spec> = {
  PASS_RECOMMENDED: { tone: 'ok', icon: 'checkCircle' },
  MINOR_REVISION: { tone: 'info', icon: 'edit' },
  MAJOR_REVISION: { tone: 'warn', icon: 'alert' },
  SUBSTANTIAL_REWORK: { tone: 'bad', icon: 'xCircle' },
  NEEDS_VERIFICATION: { tone: 'warn', icon: 'shield' },
  NOT_SCORABLE: { tone: 'neutral', icon: 'info' },
}

const SEVERITY: Record<string, Spec> = {
  critical: { tone: 'bad', icon: 'xCircle' },
  major: { tone: 'warn', icon: 'alert' },
  minor: { tone: 'info', icon: 'info' },
  info: { tone: 'neutral', icon: 'info' },
}

const COMPLIANCE: Record<string, Spec> = {
  pass: { tone: 'ok', icon: 'checkCircle' },
  fail: { tone: 'bad', icon: 'xCircle' },
  needs_verification: { tone: 'warn', icon: 'shield' },
  not_applicable: { tone: 'neutral', icon: 'info' },
  incomplete: { tone: 'neutral', icon: 'clock' },
}

const OBSERVED: Record<string, Spec> = {
  pass: { tone: 'ok', icon: 'check' },
  fail: { tone: 'bad', icon: 'xCircle' },
  unknown: { tone: 'warn', icon: 'user' },
  not_applicable: { tone: 'neutral', icon: 'info' },
  error: { tone: 'bad', icon: 'alert' },
}

type Props = { value: string | null | undefined }

function StatusPill({ value, map, labels }: Props & { map: Record<string, Spec>; labels: Record<string, string> }) {
  if (!value) return <Pill>—</Pill>
  const s = map[value] ?? { tone: 'neutral' as Tone, icon: 'info' as IconName }
  return (
    <Pill tone={s.tone} icon={s.icon}>
      {labels[value] ?? value}
    </Pill>
  )
}

const RUN: Record<string, Spec> = {
  QUEUED: { tone: 'neutral', icon: 'clock' },
  PROCESSING: { tone: 'info', icon: 'loader' },
  COMPLETED: { tone: 'ok', icon: 'checkCircle' },
  INCOMPLETE: { tone: 'warn', icon: 'alert' },
  FAILED: { tone: 'bad', icon: 'xCircle' },
}

export const IsbnBadge = ({ value }: Props) => <StatusPill value={value} map={ISBN} labels={ISBN_LABELS} />
export const EditorialBadge = ({ value }: Props) => <StatusPill value={value} map={EDITORIAL} labels={EDITORIAL_LABELS} />
export const SeverityBadge = ({ value }: Props) => <StatusPill value={value} map={SEVERITY} labels={SEVERITY_LABELS} />
export const ComplianceBadge = ({ value }: Props) => <StatusPill value={value} map={COMPLIANCE} labels={COMPLIANCE_LABELS} />
export const ObservedBadge = ({ value }: Props) => <StatusPill value={value} map={OBSERVED} labels={OBSERVED_LABELS} />
export const RunStatusBadge = ({ value }: Props) => <StatusPill value={value} map={RUN} labels={RUN_STATUS_LABELS} />

const VERIFY: Record<string, Spec> = {
  UNREVIEWED: { tone: 'neutral', icon: 'clock' },
  CONFIRMED: { tone: 'warn', icon: 'check' },
  FALSE_POSITIVE: { tone: 'neutral', icon: 'xCircle' },
  NEEDS_FURTHER_CHECK: { tone: 'info', icon: 'search' },
  RESOLVED_IN_NEW_VERSION: { tone: 'ok', icon: 'checkCircle' },
}

const DECISION: Record<string, Spec> = {
  ACCEPTED_FOR_NEXT_STAGE: { tone: 'ok', icon: 'checkCircle' },
  REVISION_REQUIRED: { tone: 'warn', icon: 'edit' },
  REJECTED: { tone: 'bad', icon: 'xCircle' },
  PENDING_VERIFICATION: { tone: 'info', icon: 'clock' },
  SCREENING_INCOMPLETE: { tone: 'neutral', icon: 'alert' },
}

export const VerifyBadge = ({ value }: Props) => <StatusPill value={value} map={VERIFY} labels={VERIFY_LABELS} />
export const DecisionBadge = ({ value }: Props) => <StatusPill value={value} map={DECISION} labels={DECISION_LABELS} />
