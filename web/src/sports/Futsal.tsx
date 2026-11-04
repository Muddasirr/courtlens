// Futsal UI = the CourtLens frontend (../frontend/src), mounted at its own routes inside the shell.
import { FacilityHome, LabelPage, MatchPage, Phase0Page, PublicReportPage } from '@futsal/App'
import type { ReactNode } from 'react'

const Scope = ({ children }: { children: ReactNode }) => <div className="sl-futsal sport-scope">{children}</div>

export const FutsalHome = () => (
  <Scope>
    <FacilityHome />
  </Scope>
)
export const FutsalMatch = () => (
  <Scope>
    <MatchPage />
  </Scope>
)
export const FutsalLabel = () => (
  <Scope>
    <LabelPage />
  </Scope>
)
export const FutsalShare = () => (
  <Scope>
    <PublicReportPage />
  </Scope>
)
export const FutsalPhase0 = () => (
  <Scope>
    <Phase0Page />
  </Scope>
)
