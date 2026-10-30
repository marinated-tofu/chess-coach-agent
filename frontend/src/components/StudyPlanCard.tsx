import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from '@tanstack/react-router';
import { AlertCircle, ArrowRight, CalendarDays, Check, Clock, Loader2 } from 'lucide-react';
import { createTrainingSession } from '../lib/api';
import { createStudyPlan, getStudyPlan, studyPlanKey, type PlanTask, type StudyPlan } from '../lib/studyPlanApi';
import type { Platform } from '../lib/types';
import { planNoticeKey } from '../lib/limitNotice';
import { LimitNoticeLine } from './LimitNoticeLine';
import { Skeleton } from './Skeleton';
import './StudyPlanCard.css';
import { isAccessDenied } from '../lib/access';

const ACTION_LABEL: Record<PlanTask['kind'], string> = {
  due_review: 'Start review',
  leak_practice: 'Practice',
  game_review: 'Review game',
  repertoire_review: 'Start drill',
  repertoire_build: 'Open repertoire'
};

function weekday(iso: string, style: 'short' | 'long' = 'short') {
  const [year, month, day] = iso.split('-').map(Number);
  return new Intl.DateTimeFormat(undefined, { weekday: style, timeZone: 'UTC' }).format(new Date(Date.UTC(year, month - 1, day)));
}

function TaskRow({ task, player, platform }: { task: PlanTask; player: string; platform: Platform }) {
  const navigate = useNavigate();
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState('');

  async function startPractice() {
    setStarting(true);
    setError('');
    try {
      const session = await createTrainingSession(player, platform, task.theme ?? undefined, undefined, task.session_mode ?? 'mixed');
      await navigate({ to: '/practice/$sessionId', params: { sessionId: session.id } });
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not start practice');
      setStarting(false);
    }
  }

  function open() {
    if (task.kind === 'game_review' && task.game_id) {
      void navigate({ to: '/games/$gameId', params: { gameId: task.game_id }, search: { moment: task.moment_id ?? undefined } });
    } else if (task.kind === 'due_review' || task.kind === 'leak_practice') {
      void startPractice();
    } else {
      const search = task.kind === 'repertoire_review'
        ? { color: task.repertoire_color, drill: true }
        : {};
      void navigate({ to: '/repertoire', search: search as never });
    }
  }

  const done = task.status === 'done';
  return (
    <li className={`plan-task ${task.status}`}>
      <span className="plan-task-mark" aria-hidden="true">
        {done ? <Check size={14} /> : task.status === 'overdue' ? <Clock size={14} /> : null}
      </span>
      <div className="plan-task-copy">
        <p className="plan-task-title">{task.title}</p>
        <p className="plan-task-detail">{task.detail}</p>
        {error && <p className="today-card-error" role="alert"><AlertCircle size={15} /> {error}</p>}
      </div>
      <div className="plan-task-side">
        <span className="plan-task-progress num">
          {done ? 'Done' : `${task.progress} of ${task.target}`}
          {task.status === 'overdue' && <span className="plan-task-late"> · from an earlier day</span>}
        </span>
        {!done && (
          <button type="button" className="secondary" onClick={open} disabled={starting}>
            {starting ? <Loader2 className="spin" size={16} /> : <ArrowRight size={16} />} {ACTION_LABEL[task.kind]}
          </button>
        )}
      </div>
    </li>
  );
}

function PlanWeek({ plan, player, platform }: { plan: StudyPlan; player: string; platform: Platform }) {
  const [picked, setPicked] = useState<number | null>(null);
  const selected = picked ?? plan.today_index;
  const onToday = selected === plan.today_index;
  const carried = onToday
    ? plan.days.slice(0, selected).flatMap((day) => day.tasks.filter((task) => task.status === 'overdue'))
    : [];
  const tasks = [...carried, ...plan.days[selected].tasks];
  const share = plan.total_tasks ? (plan.done_tasks / plan.total_tasks) * 100 : 0;

  return (
    <>
      <div className="plan-summary">
        <p className="today-card-body">{plan.summary}</p>
        {plan.rationale
          ? <p className="plan-rationale">{plan.rationale}</p>
          : <LimitNoticeLine noticeKey={planNoticeKey(plan.id)} />}
      </div>
      <div className="plan-meter" role="img" aria-label={`${plan.done_tasks} of ${plan.total_tasks} tasks done`}>
        <div className="plan-meter-track"><span style={{ transform: `scaleX(${share / 100})` }} /></div>
        <span className="num">{plan.done_tasks} of {plan.total_tasks} done</span>
      </div>
      <div className="plan-days" role="group" aria-label="Days this week">
        {plan.days.map((day) => {
          const open = day.tasks.filter((task) => task.status !== 'done').length;
          return (
            <button
              key={day.date}
              type="button"
              className={`plan-day${day.index === plan.today_index ? ' today' : ''}`}
              aria-pressed={day.index === selected}
              aria-label={`${weekday(day.date, 'long')}, ${open ? `${open} open` : 'all done'}`}
              onClick={() => setPicked(day.index)}
            >
              <span>{weekday(day.date)}</span>
              <span className={`plan-day-dot${open ? '' : ' done'}`} aria-hidden="true" />
            </button>
          );
        })}
      </div>
      <ul className="plan-tasks">
        {tasks.map((task) => <TaskRow key={task.id} task={task} player={player} platform={platform} />)}
      </ul>
    </>
  );
}

export function StudyPlanCard({ player, platform }: { player: string; platform: Platform }) {
  const queryClient = useQueryClient();
  const key = studyPlanKey(platform, player);
  // No stale time: coming back from a session must show the new progress.
  const query = useQuery({ queryKey: key, queryFn: () => getStudyPlan(player, platform) });
  const build = useMutation({
    mutationFn: () => createStudyPlan(player, platform),
    onSuccess: (data) => queryClient.setQueryData(key, data)
  });
  const plan = query.data?.plan;
  const last = query.data?.last_plan;

  return (
    <section className="today-card plan-card" aria-labelledby="plan-title">
      <header className="today-card-title">
        <span aria-hidden="true"><CalendarDays size={17} /></span>
        <h2 id="plan-title">This week's plan</h2>
      </header>
      {query.isPending && <Skeleton lines={3} label="Loading your study plan" />}
      {isAccessDenied(query.error) && <p className="today-card-body">This player's plan is private.</p>}
      {query.isError && !isAccessDenied(query.error) && (
        <p className="today-card-error" role="alert">
          <AlertCircle size={15} /> Could not load your study plan.
          <button type="button" className="today-text-button" onClick={() => void query.refetch()}>Retry</button>
        </p>
      )}
      {plan && <PlanWeek plan={plan} player={player} platform={platform} />}
      {query.isSuccess && !plan && (
        <>
          <p className="today-card-body">
            {last
              ? `Your last plan ended with ${last.done_tasks} of ${last.total_tasks} tasks done. Build the next one from your latest games.`
              : 'Seven days of tasks built from your leaks, due reviews and repertoire. Progress updates as you play through them.'}
          </p>
          {build.isSuccess && !build.data.plan && (
            <p className="today-card-body">Nothing to plan yet. Sync a few analyzed games first.</p>
          )}
          {build.isError && <p className="today-card-error" role="alert"><AlertCircle size={15} /> {(build.error as Error).message}</p>}
          <div className="today-card-action">
            <button type="button" className="secondary" onClick={() => build.mutate()} disabled={build.isPending}>
              {build.isPending ? <Loader2 className="spin" size={16} /> : <ArrowRight size={16} />} Build my week
            </button>
          </div>
        </>
      )}
    </section>
  );
}
