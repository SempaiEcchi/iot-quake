# test/Makefile
CXX      ?= c++
CXXFLAGS ?= -std=c++17 -Wall -Wextra -O0 -g

test_detector: test_detector.cpp ../firmware/node/detector.cpp
	$(CXX) $(CXXFLAGS) -I../firmware/node -o $@ $^

.PHONY: run clean
run: test_detector
	./test_detector

clean:
	rm -f test_detector
