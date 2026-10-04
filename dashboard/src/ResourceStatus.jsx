const timestamp = new Intl.DateTimeFormat('ko-KR', {
  timeZone: 'Asia/Seoul', dateStyle: 'short', timeStyle: 'medium',
})

export default function ResourceStatus({ resources }) {
  return (
    <section className="resource-status" aria-label="데이터 갱신 상태">
      <h2>데이터 갱신 상태</h2>
      <ul>
        {resources.map(([label, resource]) => (
          <li key={label} className={resource.error ? 'resource-status__error' : ''}>
            <strong>{label}</strong>
            <span role={resource.error ? 'alert' : undefined}>{resource.error
              ? `${resource.data !== null ? '갱신 실패 · 이전 응답 유지' : '데이터 요청 실패'}: ${resource.error}`
              : resource.lastSuccess
                ? resource.data?.available === false ? '데이터 준비 중' : '응답 확인'
                : '요청 대기 중'}</span>
            <small>마지막 성공 응답: {resource.lastSuccess ? `${timestamp.format(new Date(resource.lastSuccess))} (한국 시간)` : '없음'}</small>
          </li>
        ))}
      </ul>
      <p>응답 확인 시각은 시세 관측 시각과 다릅니다. 각 화면의 관측일과 출처를 함께 확인하세요.</p>
    </section>
  )
}
