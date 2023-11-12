from atsc.logic import Timer


def test_on_timer():
    delay = 5
    t1 = Timer(delay)
    t2 = Timer(delay, step=-1)
    t3 = Timer(delay)
    t4 = Timer(delay, step=-1)
    
    for i in range(100):
        signal = 20 > i > 10 or 50 > i > 40 or 73 > i > 70
        
        print(f'{i:0>4}\tsignal={int(signal)}\t'
              f't1={t1.elapsed:>3}\tt2={t2.elapsed:>3}\t'
              f't3={t3.elapsed:>3}\tt4={t4.elapsed:>3}\t'
              f't1={t1.poll(signal):<1}\tt2={t2.poll(signal):<1}\t'
              f't3={t3.poll(not signal):<1}\tt4={t4.poll(not signal):<1}')
        
if __name__ == '__main__':
    test_on_timer()
